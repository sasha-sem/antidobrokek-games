from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.errors import QuizError
from app.core.security import hash_token, new_token, verify_token
from app.models.tables import (
    Answer,
    Author,
    Meme,
    Pack,
    PackAuthor,
    PackItem,
    Player,
    QuestionRun,
    Reaction,
    Room,
    RoomState,
    utcnow,
)
from app.services.media import MediaStorage

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
OPEN_ROOM_STATES = {
    RoomState.LOBBY.value,
    RoomState.PRELOADING.value,
    RoomState.QUESTION.value,
    RoomState.REVEAL.value,
}


class GameService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings,
        storage: MediaStorage,
    ):
        self.sessions = session_factory
        self.settings = settings
        self.storage = storage

    async def _room(self, session, code: str) -> Room:
        room = await session.scalar(select(Room).where(Room.code == code.upper()))
        if not room:
            raise QuizError("Комната не найдена", code="room_not_found", status_code=404)
        return room

    async def create_room(self, pack_id: str, grace_seconds: int) -> tuple[Room, str]:
        if not 0 <= grace_seconds <= 60:
            raise QuizError("Дополнительное время должно быть от 0 до 60 секунд")
        token = new_token()
        async with self.sessions() as session, session.begin():
            open_room = await session.scalar(select(Room.id).where(Room.state.in_(OPEN_ROOM_STATES)))
            if open_room:
                raise QuizError(
                    "Уже есть незакрытая комната",
                    code="active_room_exists",
                    status_code=409,
                )
            pack = await session.get(Pack, pack_id)
            if not pack or pack.status != "ACTIVE":
                raise QuizError("Активный пак не найден", code="pack_not_active")
            for _ in range(50):
                code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
                if not await session.scalar(select(Room.id).where(Room.code == code)):
                    break
            else:  # pragma: no cover - astronomically unlikely
                raise QuizError("Не удалось создать уникальный код")
            room = Room(
                code=code,
                pack_id=pack_id,
                state=RoomState.LOBBY.value,
                host_token_hash=hash_token(token),
                question_grace_seconds=grace_seconds,
            )
            session.add(room)
            await session.flush()
            return room, token

    async def join(self, code: str, display_name: str, identity_id: str) -> tuple[Player, str]:
        token = new_token()
        async with self.sessions() as session, session.begin():
            room = await self._room(session, code)
            existing = await session.scalar(
                select(Player).where(Player.room_id == room.id, Player.identity_id == identity_id)
            )
            if existing:
                existing.reconnect_token_hash = hash_token(token)
                existing.last_seen_at = utcnow()
                return existing, token
            if room.state != RoomState.LOBBY.value:
                raise QuizError("Игра уже началась", code="room_started", status_code=409)
            player_count = await session.scalar(
                select(func.count(Player.id)).where(Player.room_id == room.id)
            )
            if int(player_count or 0) >= self.settings.max_players:
                raise QuizError("Комната заполнена", code="room_full", status_code=409)
            duplicate = await session.scalar(
                select(Player.id).where(
                    Player.room_id == room.id,
                    Player.display_name_normalized == display_name.casefold(),
                )
            )
            if duplicate:
                raise QuizError("Это имя уже занято", code="name_taken", status_code=409)
            player = Player(
                room_id=room.id,
                identity_id=identity_id,
                display_name=display_name,
                display_name_normalized=display_name.casefold(),
                reconnect_token_hash=hash_token(token),
                is_connected=False,
                is_ready=False,
            )
            session.add(player)
            await session.flush()
            return player, token

    async def authenticate(self, code: str, role: str, token: str) -> tuple[Room, Player | None]:
        async with self.sessions() as session:
            room = await self._room(session, code)
            if role == "host":
                if not verify_token(token, room.host_token_hash):
                    raise QuizError("Неверный токен ведущего", code="unauthorized", status_code=401)
                return room, None
            if role != "player":
                raise QuizError("Неизвестная роль", code="unauthorized", status_code=401)
            players = (await session.scalars(select(Player).where(Player.room_id == room.id))).all()
            player = next((item for item in players if verify_token(token, item.reconnect_token_hash)), None)
            if not player:
                raise QuizError("Неверный reconnect token", code="unauthorized", status_code=401)
            return room, player

    async def set_connection(self, player_id: str, connected: bool) -> None:
        async with self.sessions() as session, session.begin():
            player = await session.get(Player, player_id)
            if player:
                player.is_connected = connected
                player.last_seen_at = utcnow()

    async def reset_connections(self) -> None:
        async with self.sessions() as session, session.begin():
            players = (await session.scalars(select(Player).where(Player.is_connected.is_(True)))).all()
            for player in players:
                player.is_connected = False
                player.last_seen_at = utcnow()

    async def recoverable_rooms(self) -> list[Room]:
        async with self.sessions() as session:
            return list((await session.scalars(select(Room).where(Room.state.in_(OPEN_ROOM_STATES)))).all())

    async def current_question_timing(self, room_id: str) -> dict[str, Any]:
        async with self.sessions() as session:
            room = await session.get(Room, room_id)
            if not room or not room.current_position:
                raise QuizError("Текущий вопрос не найден", code="question_not_found")
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id,
                    QuestionRun.position == room.current_position,
                )
            )
            if not run:
                raise QuizError("Текущий вопрос не найден", code="question_not_found")
            return {
                "starts_at": run.started_at,
                "ends_at": run.ends_at,
                "grace_seconds": room.question_grace_seconds,
                "revealed_at": run.revealed_at,
            }

    async def set_player_ready(self, room_id: str, player_id: str, ready: bool = True) -> None:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            player = await session.get(Player, player_id)
            if not room or not player or player.room_id != room.id:
                raise QuizError("Игрок не принадлежит комнате", code="forbidden")
            if room.state != RoomState.LOBBY.value:
                raise QuizError("Готовность можно менять только в лобби", code="invalid_state")
            player.is_ready = ready

    async def _current_item(self, session, room: Room) -> tuple[PackItem, Meme]:
        row = (
            await session.execute(
                select(PackItem, Meme)
                .join(Meme, Meme.id == PackItem.meme_id)
                .where(PackItem.pack_id == room.pack_id, PackItem.position == room.current_position)
            )
        ).one_or_none()
        if not row:
            raise QuizError("Текущий вопрос не найден", code="question_not_found")
        return row[0], row[1]

    async def preload(self, room_id: str, *, first: bool = False) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            if not room:
                raise QuizError("Комната не найдена", status_code=404)
            expected = RoomState.LOBBY.value if first else RoomState.REVEAL.value
            if room.state != expected:
                raise QuizError(f"Нельзя перейти к preload из {room.state}", code="invalid_state")
            if first:
                players = (
                    await session.scalars(select(Player).where(Player.room_id == room.id))
                ).all()
                if not players:
                    raise QuizError("Для старта нужен хотя бы одиной игрок", code="no_players")
                if any(player.is_connected and not player.is_ready for player in players):
                    raise QuizError("Не все подключённые игроки готовы", code="players_not_ready")
                room.current_position = 1
                room.started_at = utcnow()
            else:
                pack = await session.get(Pack, room.pack_id)
                if room.current_position >= pack.question_count:
                    return await self._finish_in_session(session, room)
                room.current_position += 1
            room.state = RoomState.PRELOADING.value
            _, meme = await self._current_item(session, room)
            return await self._preload_payload(session, room, meme)

    async def _preload_payload(self, session, room: Room, meme: Meme) -> dict[str, Any]:
        pack = await session.get(Pack, room.pack_id)
        authors = (
            await session.execute(
                select(Author.id, Author.display_name)
                .join(PackAuthor, PackAuthor.author_id == Author.id)
                .where(PackAuthor.pack_id == room.pack_id)
                .order_by(PackAuthor.position)
            )
        ).all()
        return {
            "position": room.current_position,
            "question_count": pack.question_count,
            "media_url": self.storage.get_public_url(meme.media_path),
            "duration_ms": meme.duration_ms,
            "authors": [{"id": row.id, "display_name": row.display_name} for row in authors],
            "preload_timeout_seconds": self.settings.preload_timeout_seconds,
        }

    async def start_question(self, room_id: str) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            if not room or room.state != RoomState.PRELOADING.value:
                raise QuizError("Вопрос можно запустить только из PRELOADING", code="invalid_state")
            _, meme = await self._current_item(session, room)
            now = utcnow()
            starts_at = now + timedelta(seconds=self.settings.question_start_delay_seconds)
            ends_at = starts_at + timedelta(milliseconds=meme.duration_ms)
            run = QuestionRun(
                room_id=room.id,
                meme_id=meme.id,
                position=room.current_position,
                started_at=starts_at,
                ends_at=ends_at,
            )
            session.add(run)
            room.state = RoomState.QUESTION.value
            await session.flush()
            return {
                "question_run_id": run.id,
                "position": room.current_position,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "grace_seconds": room.question_grace_seconds,
            }

    async def submit_answer(self, room_id: str, player_id: str, author_id: str) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            player = await session.get(Player, player_id)
            if not room or not player or player.room_id != room.id:
                raise QuizError("Игрок не принадлежит комнате", code="forbidden")
            if room.state != RoomState.QUESTION.value:
                raise QuizError("Ответы сейчас не принимаются", code="answer_closed")
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id, QuestionRun.position == room.current_position
                )
            )
            now = utcnow()
            if now > run.ends_at + timedelta(seconds=room.question_grace_seconds):
                raise QuizError("Время ответа истекло", code="answer_closed")
            valid_author = await session.scalar(
                select(Author.id)
                .join(PackAuthor, PackAuthor.author_id == Author.id)
                .where(PackAuthor.pack_id == room.pack_id, Author.id == author_id)
            )
            if not valid_author:
                raise QuizError("Такого автора нет в паке", code="invalid_author")
            meme = await session.get(Meme, run.meme_id)
            answer = await session.scalar(
                select(Answer).where(
                    Answer.question_run_id == run.id, Answer.player_id == player.id
                )
            )
            response_time = max(0, round((now - run.started_at).total_seconds() * 1000))
            if answer:
                answer.selected_author_id = author_id
                answer.is_correct = author_id == meme.author_id
                answer.response_time_ms = response_time
                answer.updated_at = now
            else:
                answer = Answer(
                    question_run_id=run.id,
                    player_id=player.id,
                    selected_author_id=author_id,
                    is_correct=author_id == meme.author_id,
                    response_time_ms=response_time,
                    submitted_at=now,
                )
                session.add(answer)
            return {"selected_author_id": author_id, "response_time_ms": response_time}

    async def reveal(self, room_id: str, *, automatic: bool = False) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            if not room or room.state != RoomState.QUESTION.value:
                raise QuizError("Раскрытие сейчас недопустимо", code="invalid_state")
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id, QuestionRun.position == room.current_position
                )
            )
            if not automatic and utcnow() < run.ends_at:
                raise QuizError("Нельзя раскрыть ответ до конца видео", code="video_not_finished")
            run.revealed_at = utcnow()
            room.state = RoomState.REVEAL.value
            meme = await session.get(Meme, run.meme_id)
            author = await session.get(Author, meme.author_id)
            correct_count = await session.scalar(
                select(func.count(Answer.id)).where(
                    Answer.question_run_id == run.id, Answer.is_correct.is_(True)
                )
            )
            return {
                "question_run_id": run.id,
                "position": room.current_position,
                "correct_author": {"id": author.id, "display_name": author.display_name},
                "correct_count": int(correct_count or 0),
            }

    async def set_reaction(self, room_id: str, player_id: str, value: int | None) -> dict[str, Any]:
        if value not in (-1, 1, None):
            raise QuizError("Реакция должна быть -1, 1 или null", code="invalid_reaction")
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            player = await session.get(Player, player_id)
            if not room or not player or player.room_id != room.id:
                raise QuizError("Игрок не принадлежит комнате", code="forbidden")
            if room.state != RoomState.REVEAL.value:
                raise QuizError("Реакции доступны после раскрытия", code="invalid_state")
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id, QuestionRun.position == room.current_position
                )
            )
            reaction = await session.scalar(
                select(Reaction).where(
                    Reaction.meme_id == run.meme_id, Reaction.identity_id == player.identity_id
                )
            )
            if value is None:
                if reaction:
                    await session.delete(reaction)
            elif reaction:
                reaction.value = value
                reaction.last_room_id = room.id
                reaction.updated_at = utcnow()
            else:
                session.add(
                    Reaction(
                        meme_id=run.meme_id,
                        identity_id=player.identity_id,
                        value=value,
                        last_room_id=room.id,
                    )
                )
            return {"value": value}

    async def finish(self, room_id: str) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            if not room or room.state in (RoomState.CLOSED.value, RoomState.CANCELLED.value):
                raise QuizError("Игру нельзя завершить в этом состоянии", code="invalid_state")
            return await self._finish_in_session(session, room)

    async def _finish_in_session(self, session, room: Room) -> dict[str, Any]:
        room.state = RoomState.FINISHED.value
        room.finished_at = utcnow()
        await session.flush()
        return {
            "scoreboard": await self._final_scoreboard(session, room),
            "popular_meme": await self._popular_meme(session, room.id),
        }

    async def close(self, room_id: str) -> None:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            if not room:
                raise QuizError("Комната не найдена", status_code=404)
            room.state = RoomState.CLOSED.value
            room.closed_at = utcnow()

    async def kick(self, room_id: str, player_id: str) -> None:
        async with self.sessions() as session, session.begin():
            room = await session.get(Room, room_id)
            player = await session.get(Player, player_id)
            if not room or room.state != RoomState.LOBBY.value:
                raise QuizError("Удалять игроков можно только в лобби", code="invalid_state")
            if not player or player.room_id != room.id:
                raise QuizError("Игрок не найден", code="player_not_found")
            await session.delete(player)

    async def _scoreboard(self, session, room_id: str) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                select(
                    Player.id,
                    Player.display_name,
                    func.coalesce(func.sum(case((Answer.is_correct.is_(True), 1), else_=0)), 0).label("score"),
                )
                .outerjoin(Answer, Answer.player_id == Player.id)
                .where(Player.room_id == room_id)
                .group_by(Player.id)
                .order_by(func.coalesce(func.sum(case((Answer.is_correct.is_(True), 1), else_=0)), 0).desc(), Player.joined_at)
            )
        ).all()
        scoreboard = []
        previous_score: int | None = None
        rank = 0
        for index, row in enumerate(rows, start=1):
            score = int(row.score)
            if score != previous_score:
                rank = index
            scoreboard.append({"rank": rank, "player_id": row.id, "display_name": row.display_name, "score": score})
            previous_score = score
        return scoreboard

    async def _popular_meme(self, session, room_id: str) -> dict[str, Any] | None:
        row = (
            await session.execute(
                select(
                    Meme.id,
                    func.sum(Reaction.value).label("rating"),
                    func.count(Reaction.id).label("votes"),
                )
                .join(QuestionRun, QuestionRun.meme_id == Meme.id)
                .join(Reaction, Reaction.meme_id == Meme.id)
                .where(QuestionRun.room_id == room_id, Reaction.last_room_id == room_id)
                .group_by(Meme.id)
                .order_by(func.sum(Reaction.value).desc(), func.count(Reaction.id).desc())
                .limit(1)
            )
        ).one_or_none()
        return {"meme_id": row.id, "rating": int(row.rating), "votes": int(row.votes)} if row else None

    async def _final_scoreboard(self, session, room: Room) -> list[dict[str, Any]]:
        scoreboard = await self._scoreboard(session, room.id)
        pack = await session.get(Pack, room.pack_id)
        evaluated = dict(
            (
                await session.execute(
                    select(Player.id, func.count(Reaction.id))
                    .outerjoin(
                        Reaction,
                        (Reaction.identity_id == Player.identity_id)
                        & (Reaction.last_room_id == room.id),
                    )
                    .where(Player.room_id == room.id)
                    .group_by(Player.id)
                )
            ).all()
        )
        for row in scoreboard:
            row["total_questions"] = pack.question_count
            row["accuracy_percent"] = round(row["score"] / pack.question_count * 100, 2)
            row["evaluated_count"] = int(evaluated.get(row["player_id"], 0))
        return scoreboard

    async def snapshot(self, code: str, player_id: str | None = None) -> dict[str, Any]:
        async with self.sessions() as session:
            room = await self._room(session, code)
            pack = await session.get(Pack, room.pack_id)
            players = (
                await session.scalars(select(Player).where(Player.room_id == room.id).order_by(Player.joined_at))
            ).all()
            payload: dict[str, Any] = {
                "room": {
                    "id": room.id,
                    "code": room.code,
                    "state": room.state,
                    "current_position": room.current_position,
                },
                "pack": {"title": pack.title, "question_count": pack.question_count},
                "players": [
                    {
                        "id": player.id,
                        "display_name": player.display_name,
                        "is_connected": player.is_connected,
                        "is_ready": player.is_ready,
                    }
                    for player in players
                ],
                "scoreboard": await self._scoreboard(session, room.id),
            }
            if room.current_position:
                _, meme = await self._current_item(session, room)
                current: dict[str, Any] = {
                    "position": room.current_position,
                    "question_count": pack.question_count,
                    "media_url": self.storage.get_public_url(meme.media_path),
                    "duration_ms": meme.duration_ms,
                }
                run = await session.scalar(
                    select(QuestionRun).where(
                        QuestionRun.room_id == room.id,
                        QuestionRun.position == room.current_position,
                    )
                )
                if run:
                    current.update({"starts_at": run.started_at, "ends_at": run.ends_at})
                    if room.state in (RoomState.REVEAL.value, RoomState.FINISHED.value):
                        author = await session.get(Author, meme.author_id)
                        current["correct_author"] = {"id": author.id, "display_name": author.display_name}
                    if player_id:
                        player = await session.get(Player, player_id)
                        answer = await session.scalar(
                            select(Answer).where(
                                Answer.question_run_id == run.id, Answer.player_id == player_id
                            )
                        )
                        reaction = await session.scalar(
                            select(Reaction).where(
                                Reaction.meme_id == meme.id,
                                Reaction.identity_id == player.identity_id,
                            )
                        )
                        current["selected_author_id"] = answer.selected_author_id if answer else None
                        current["is_correct"] = answer.is_correct if answer else False
                        current["reaction"] = reaction.value if reaction else None
                current.update(await self._preload_payload(session, room, meme))
                payload["current_question"] = current
            if room.state == RoomState.FINISHED.value:
                payload["scoreboard"] = await self._final_scoreboard(session, room)
                payload["popular_meme"] = await self._popular_meme(session, room.id)
            return payload

    async def player_answer_for_reveal(self, room_id: str, player_id: str) -> dict[str, Any]:
        async with self.sessions() as session:
            room = await session.get(Room, room_id)
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id, QuestionRun.position == room.current_position
                )
            )
            answer = await session.scalar(
                select(Answer).where(Answer.question_run_id == run.id, Answer.player_id == player_id)
            )
            return {
                "selected_author_id": answer.selected_author_id if answer else None,
                "is_correct": answer.is_correct if answer else False,
            }

    async def connected_answer_status(self, room_id: str) -> tuple[int, int]:
        async with self.sessions() as session:
            room = await session.get(Room, room_id)
            run = await session.scalar(
                select(QuestionRun).where(
                    QuestionRun.room_id == room.id, QuestionRun.position == room.current_position
                )
            )
            connected = await session.scalar(
                select(func.count(Player.id)).where(Player.room_id == room_id, Player.is_connected.is_(True))
            )
            answered = await session.scalar(
                select(func.count(Answer.id))
                .join(Player, Player.id == Answer.player_id)
                .where(Answer.question_run_id == run.id, Player.is_connected.is_(True))
            )
            return int(connected or 0), int(answered or 0)

    async def public_snapshot(self, code: str) -> dict[str, Any]:
        payload = await self.snapshot(code)
        payload.pop("current_question", None)
        return payload

    async def leave(self, code: str, token: str) -> None:
        room, player = await self.authenticate(code, "player", token)
        await self.set_connection(player.id, False)
