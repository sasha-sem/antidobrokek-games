from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from app.core.errors import QuizError
from app.models.tables import Room, utcnow
from app.services.game import GameService


def envelope(event_type: str, payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": event_type,
        "server_time": utcnow().isoformat(timespec="milliseconds") + "Z",
        "payload": payload,
    }
    if request_id:
        message["request_id"] = request_id
    return jsonable_encoder(
        message,
        custom_encoder={
            datetime: lambda value: (
                value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            )
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        },
    )


class ConnectionManager:
    def __init__(self, game: GameService):
        self.game = game
        self.hosts: dict[str, WebSocket] = {}
        self.players: dict[str, dict[str, WebSocket]] = defaultdict(dict)
        self.media_ready: dict[str, set[str]] = defaultdict(set)
        self.preload_tasks: dict[str, asyncio.Task] = {}
        self.question_tasks: dict[str, asyncio.Task] = {}
        self.reveal_tasks: dict[str, asyncio.Task] = {}
        self.transition_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def send(
        self,
        socket: WebSocket,
        event_type: str,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        await socket.send_json(envelope(event_type, payload, request_id))

    async def broadcast(
        self, room_id: str, event_type: str, payload: dict[str, Any], *, include_host: bool = True
    ) -> None:
        sockets = list(self.players[room_id].values())
        if include_host and room_id in self.hosts:
            sockets.append(self.hosts[room_id])
        for socket in sockets:
            try:
                await self.send(socket, event_type, payload)
            except Exception:
                pass

    async def register(
        self, socket: WebSocket, room: Room, role: str, player_id: str | None
    ) -> None:
        if role == "host":
            previous = self.hosts.get(room.id)
            if previous and previous is not socket:
                await previous.close(code=4001, reason="Ведущий подключился в другой вкладке")
            self.hosts[room.id] = socket
        else:
            previous = self.players[room.id].get(player_id)
            if previous and previous is not socket:
                await previous.close(code=4001, reason="Игрок переподключился")
            self.players[room.id][player_id] = socket
            await self.game.set_connection(player_id, True)

    async def unregister(self, socket: WebSocket, room: Room, role: str, player_id: str | None) -> None:
        room_id = room.id
        if role == "host":
            if self.hosts.get(room_id) is socket:
                self.hosts.pop(room_id, None)
            return
        if self.players[room_id].get(player_id) is socket:
            self.players[room_id].pop(player_id, None)
            await self.game.set_connection(player_id, False)
            await self.broadcast(
                room_id,
                "player_connection_changed",
                {"player_id": player_id, "is_connected": False},
            )
            await self._broadcast_snapshot(room)

    async def authenticated_snapshot(
        self, socket: WebSocket, room: Room, role: str, player_id: str | None
    ) -> None:
        await self.send(socket, "authenticated", {"role": role, "player_id": player_id})
        await self.send(socket, "room_snapshot", await self.game.snapshot(room.code, player_id))
        if player_id:
            await self.broadcast(
                room.id,
                "player_connection_changed",
                {"player_id": player_id, "is_connected": True},
            )
            await self._broadcast_snapshot(room)

    async def _broadcast_snapshot(self, room: Room) -> None:
        host = self.hosts.get(room.id)
        if host:
            await self.send(host, "room_snapshot", await self.game.snapshot(room.code))
        for player_id, socket in list(self.players[room.id].items()):
            await self.send(socket, "room_snapshot", await self.game.snapshot(room.code, player_id))

    def _replace_task(self, mapping: dict[str, asyncio.Task], room_id: str, coroutine) -> None:
        existing = mapping.pop(room_id, None)
        if existing:
            existing.cancel()
        task = asyncio.create_task(coroutine)
        mapping[room_id] = task

    async def recover(self) -> None:
        await self.game.reset_connections()
        for room in await self.game.recoverable_rooms():
            try:
                if room.state == "PRELOADING":
                    self._replace_task(self.preload_tasks, room.id, self._preload_timeout(room))
                elif room.state == "QUESTION":
                    timing = await self.game.current_question_timing(room.id)
                    self._replace_task(
                        self.question_tasks,
                        room.id,
                        self._question_timer(room, timing),
                    )
                elif room.state == "REVEAL":
                    timing = await self.game.current_question_timing(room.id)
                    revealed_at = timing.get("revealed_at") or utcnow()
                    elapsed = max(0.0, (utcnow() - revealed_at).total_seconds())
                    delay = max(0.0, self.game.settings.reveal_duration_seconds - elapsed)
                    self._replace_task(
                        self.reveal_tasks,
                        room.id,
                        self._advance_after_reveal(room, delay_seconds=delay),
                    )
            except QuizError:
                continue

    async def shutdown(self) -> None:
        tasks = [
            *self.preload_tasks.values(),
            *self.question_tasks.values(),
            *self.reveal_tasks.values(),
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _start_preload(self, room: Room, payload: dict[str, Any]) -> None:
        self.media_ready[room.id].clear()
        await self.broadcast(room.id, "room_state_changed", {"state": "PRELOADING"})
        await self.broadcast(room.id, "question_preload", payload)
        self._replace_task(
            self.preload_tasks,
            room.id,
            self._preload_timeout(room),
        )

    async def _preload_timeout(self, room: Room) -> None:
        try:
            await asyncio.sleep(self.game.settings.preload_timeout_seconds)
            await self._start_question(room)
        except (asyncio.CancelledError, QuizError):
            return

    async def _start_question(self, room: Room) -> None:
        task = self.preload_tasks.pop(room.id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        payload = await self.game.start_question(room.id)
        await self.broadcast(room.id, "room_state_changed", {"state": "QUESTION"})
        await self.broadcast(room.id, "question_started", payload)
        self._replace_task(self.question_tasks, room.id, self._question_timer(room, payload))

    async def _question_timer(self, room: Room, payload: dict[str, Any]) -> None:
        try:
            ends_at: datetime = payload["ends_at"]
            await asyncio.sleep(max(0, (ends_at - utcnow()).total_seconds()))
            connected, answered = await self.game.connected_answer_status(room.id)
            if connected and answered < connected:
                await asyncio.sleep(payload["grace_seconds"])
            await self._reveal(room, automatic=True)
        except (asyncio.CancelledError, QuizError):
            return

    async def _reveal(self, room: Room, *, automatic: bool) -> None:
        task = self.question_tasks.pop(room.id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        payload = await self.game.reveal(room.id, automatic=automatic)
        snapshot = await self.game.snapshot(room.code)
        next_question_at = utcnow() + timedelta(seconds=self.game.settings.reveal_duration_seconds)
        base = {
            **payload,
            "scoreboard": snapshot["scoreboard"],
            "next_question_at": next_question_at,
        }
        host = self.hosts.get(room.id)
        if host:
            await self.send(host, "question_revealed", base)
        for player_id, socket in list(self.players[room.id].items()):
            own = await self.game.player_answer_for_reveal(room.id, player_id)
            await self.send(socket, "question_revealed", {**base, **own})
        await self.broadcast(room.id, "scoreboard_updated", {"scoreboard": snapshot["scoreboard"]})
        self._replace_task(
            self.reveal_tasks,
            room.id,
            self._advance_after_reveal(room),
        )

    async def _advance_after_reveal(
        self,
        room: Room,
        *,
        delay_seconds: float | None = None,
    ) -> None:
        try:
            await asyncio.sleep(
                self.game.settings.reveal_duration_seconds
                if delay_seconds is None
                else delay_seconds
            )
            async with self.transition_locks[room.id]:
                result = await self.game.preload(room.id, first=False)
                if "position" in result:
                    await self._start_preload(room, result)
                else:
                    await self.broadcast(room.id, "game_finished", result)
        except (asyncio.CancelledError, QuizError):
            return

    async def _maybe_auto_start_game(self, room: Room) -> None:
        async with self.transition_locks[room.id]:
            snapshot = await self.game.snapshot(room.code)
            if snapshot["room"]["state"] != "LOBBY":
                return
            connected = [player for player in snapshot["players"] if player["is_connected"]]
            if not connected or not all(player["is_ready"] for player in connected):
                return
            preload = await self.game.preload(room.id, first=True)
            await self._start_preload(room, preload)

    async def _maybe_auto_start(self, room: Room) -> None:
        connected_ids = set(self.players[room.id])
        if connected_ids and connected_ids <= self.media_ready[room.id]:
            await self._start_question(room)

    async def handle(
        self,
        socket: WebSocket,
        room: Room,
        role: str,
        player_id: str | None,
        message: dict[str, Any],
    ) -> None:
        event_type = message.get("type")
        payload = message.get("payload") or {}
        request_id = message.get("request_id")
        if event_type == "ping":
            await self.send(socket, "pong", {"client_time": payload.get("client_time")}, request_id)
            return
        if event_type == "player_ready" and role == "player":
            await self.game.set_player_ready(room.id, player_id, bool(payload.get("ready", True)))
            await self.broadcast(room.id, "room_state_changed", {"state": "LOBBY"})
            await self._broadcast_snapshot(room)
            await self._maybe_auto_start_game(room)
            return
        if event_type == "player_media_ready" and role == "player":
            self.media_ready[room.id].add(player_id)
            await self.broadcast(room.id, "player_media_ready", {"player_id": player_id})
            await self._maybe_auto_start(room)
            return
        if event_type == "answer_submit" and role == "player":
            accepted = await self.game.submit_answer(room.id, player_id, str(payload.get("author_id", "")))
            await self.send(socket, "answer_accepted", accepted, request_id)
            return
        if event_type == "reaction_set" and role == "player":
            accepted = await self.game.set_reaction(room.id, player_id, payload.get("value"))
            await self.send(socket, "reaction_accepted", accepted, request_id)
            return
        if role != "host":
            raise QuizError("Это действие доступно только ведущему", code="forbidden")
        if event_type == "host_start_game":
            preload = await self.game.preload(room.id, first=True)
            await self._start_preload(room, preload)
        elif event_type == "host_start_question":
            await self._start_question(room)
        elif event_type == "host_reveal_question":
            await self._reveal(room, automatic=False)
        elif event_type == "host_next_question":
            reveal_task = self.reveal_tasks.pop(room.id, None)
            if reveal_task:
                reveal_task.cancel()
            result = await self.game.preload(room.id, first=False)
            if "position" in result:
                await self._start_preload(room, result)
            else:
                await self.broadcast(room.id, "game_finished", result)
        elif event_type == "host_finish_game":
            reveal_task = self.reveal_tasks.pop(room.id, None)
            if reveal_task:
                reveal_task.cancel()
            result = await self.game.finish(room.id)
            await self.broadcast(room.id, "game_finished", result)
        elif event_type == "host_close_room":
            await self.game.close(room.id)
            await self.broadcast(room.id, "room_state_changed", {"state": "CLOSED"})
            await self.close_room(room.id, 4000, "Ведущий закрыл комнату")
        elif event_type == "host_kick_player":
            kicked_id = str(payload.get("player_id", ""))
            target = self.players[room.id].get(kicked_id)
            if target:
                await self.send(target, "player_kicked", {})
            await self.game.kick(room.id, kicked_id)
            if target:
                await target.close(code=4003, reason="Игрок удалён ведущим")
            await self._broadcast_snapshot(room)
        else:
            raise QuizError(f"Неизвестное событие: {event_type}", code="unknown_event")

    async def close_room(self, room_id: str, code: int, reason: str) -> None:
        tasks = [
            self.preload_tasks.pop(room_id, None),
            self.question_tasks.pop(room_id, None),
            self.reveal_tasks.pop(room_id, None),
        ]
        for task in tasks:
            if task:
                task.cancel()
        sockets = list(self.players.pop(room_id, {}).values())
        host = self.hosts.pop(room_id, None)
        if host:
            sockets.append(host)
        for socket in sockets:
            try:
                await socket.close(code=code, reason=reason)
            except Exception:
                pass
