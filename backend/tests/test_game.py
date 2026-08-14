from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.errors import QuizError
from app.models.tables import (
    Answer,
    Author,
    Meme,
    Pack,
    PackAuthor,
    PackItem,
    PackStatus,
    Reaction,
)
from app.services.game import GameService


async def seed_pack(database, storage, *, duration_ms: int = 400) -> str:
    pack_id = str(uuid.uuid4())
    filename = f"{uuid.uuid4()}.mp4"
    pack_dir = storage.root / pack_id
    pack_dir.mkdir()
    (pack_dir / filename).write_bytes(b"fixture")
    async with database.session_factory() as session, session.begin():
        session.add_all(
            [
                Author(id="sasha", display_name="Саша"),
                Author(id="misha", display_name="Миша"),
            ]
        )
        meme = Meme(
            telegram_chat_id=-100,
            telegram_message_id=1,
            author_id="sasha",
            content_hash="a" * 64,
            media_path=f"{pack_id}/{filename}",
            duration_ms=duration_ms,
        )
        session.add(meme)
        await session.flush()
        session.add_all(
            [
                PackAuthor(pack_id=pack_id, author_id="sasha", position=1),
                PackAuthor(pack_id=pack_id, author_id="misha", position=2),
            ]
        )
        session.add(
            Pack(
                id=pack_id,
                title="Pack",
                schema_version=1,
                status=PackStatus.ACTIVE.value,
                question_count=1,
                created_at=datetime.now(UTC),
                activated_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            PackItem(pack_id=pack_id, position=1, meme_id=meme.id, question_external_id=str(uuid.uuid4()))
        )
    return pack_id


async def test_room_limits_state_machine_answers_and_reactions(settings, database, storage) -> None:
    pack_id = await seed_pack(database, storage)
    game = GameService(database.session_factory, settings, storage)
    room, host_token = await game.create_room(pack_id, 5)
    players = []
    tokens = []
    for index in range(5):
        player, token = await game.join(room.code, f"Player {index}", str(uuid.uuid4()))
        players.append(player)
        tokens.append(token)
    with pytest.raises(QuizError, match="заполнена"):
        await game.join(room.code, "Sixth", str(uuid.uuid4()))

    authenticated_room, host_player = await game.authenticate(room.code, "host", host_token)
    assert authenticated_room.id == room.id and host_player is None
    _, authenticated_player = await game.authenticate(room.code, "player", tokens[0])
    assert authenticated_player.id == players[0].id

    for player in players:
        await game.set_connection(player.id, True)
        await game.set_player_ready(room.id, player.id)
    preload = await game.preload(room.id, first=True)
    assert preload["authors"] == [
        {"id": "sasha", "display_name": "Саша"},
        {"id": "misha", "display_name": "Миша"},
    ]
    with pytest.raises(QuizError, match="началась"):
        await game.join(room.code, "Late", str(uuid.uuid4()))
    await game.start_question(room.id)
    await game.submit_answer(room.id, players[0].id, "misha")
    await game.submit_answer(room.id, players[0].id, "sasha")
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(Answer.id))) == 1
    with pytest.raises(QuizError, match="конца видео"):
        await game.reveal(room.id)
    revealed = await game.reveal(room.id, automatic=True)
    assert revealed["correct_author"]["id"] == "sasha"
    with pytest.raises(QuizError, match="не принимаются"):
        await game.submit_answer(room.id, players[0].id, "misha")
    await game.set_reaction(room.id, players[0].id, 1)
    await game.set_reaction(room.id, players[0].id, -1)
    async with database.session_factory() as session:
        reactions = (await session.scalars(select(Reaction))).all()
        assert len(reactions) == 1 and reactions[0].value == -1
    result = await game.finish(room.id)
    assert result["scoreboard"][0]["score"] == 1
    assert result["scoreboard"][0]["accuracy_percent"] == 100


async def test_duplicate_name_is_case_insensitive(settings, database, storage) -> None:
    pack_id = await seed_pack(database, storage)
    game = GameService(database.session_factory, settings, storage)
    room, _ = await game.create_room(pack_id, 5)
    await game.join(room.code, "Саша", str(uuid.uuid4()))
    with pytest.raises(QuizError) as caught:
        await game.join(room.code, "саша", str(uuid.uuid4()))
    assert caught.value.code == "name_taken"
