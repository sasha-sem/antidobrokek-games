from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from conftest import make_pack
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import Database
from app.main import create_app


def receive_type(socket, expected: str) -> dict:
    for _ in range(30):
        message = socket.receive_json()
        if message["type"] == expected:
            return message
    raise AssertionError(f"WebSocket event not received: {expected}")


async def create_schema(settings) -> None:
    settings.ensure_directories()
    database = Database(settings)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await database.close()


def test_rest_and_websocket_happy_path(tmp_path: Path, settings) -> None:
    asyncio.run(create_schema(settings))
    pack_path = tmp_path / "pack.zip"
    make_pack(pack_path)
    app = create_app(settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/health")
        assert health.json() == {"status": "ok"}
        with pack_path.open("rb") as pack_file:
            response = client.post(
                "/api/host/rooms",
                data={
                    "host_secret": settings.host_secret,
                    "question_grace_seconds": "1",
                },
                files={"pack": ("pack.zip", pack_file, "application/zip")},
            )
        assert response.status_code == 200, response.text
        room = response.json()

        join = client.post(
            f"/api/rooms/{room['room_code']}/join",
            json={"display_name": "Игрок", "identity_id": str(uuid.uuid4())},
        )
        assert join.status_code == 200
        player = join.json()

        with client.websocket_connect(f"/ws/rooms/{room['room_code']}") as player_socket:
            player_socket.send_json(
                {
                    "type": "authenticate",
                    "payload": {"role": "player", "token": player["reconnect_token"]},
                }
            )
            assert player_socket.receive_json()["type"] == "authenticated"
            snapshot = player_socket.receive_json()
            assert snapshot["type"] == "room_snapshot"
            assert "correct_author" not in str(snapshot)

            # The uploader participates as a regular player. Once all connected
            # players are ready, the server conducts the game automatically.
            player_socket.send_json({"type": "player_ready", "payload": {"ready": True}})
            receive_type(player_socket, "room_snapshot")
            preload = receive_type(player_socket, "question_preload")
            assert "correct_author" not in preload["payload"]
            assert "telegram_message_id" not in preload["payload"]
            assert len(preload["payload"]["authors"]) == 2

            player_socket.send_json({"type": "player_media_ready", "payload": {}})
            started = receive_type(player_socket, "question_started")
            assert started["payload"]["starts_at"] > started["server_time"]
            assert started["payload"]["starts_at"].endswith("Z")
            assert started["payload"]["ends_at"].endswith("Z")
            player_socket.send_json(
                {"type": "answer_submit", "payload": {"author_id": "sasha"}}
            )
            assert receive_type(player_socket, "answer_accepted")["payload"]["selected_author_id"] == "sasha"
            revealed = receive_type(player_socket, "question_revealed")
            assert revealed["payload"]["correct_author"]["id"] == "sasha"
            assert revealed["payload"]["is_correct"] is True
            assert revealed["payload"]["next_question_at"].endswith("Z")

            player_socket.send_json({"type": "reaction_set", "payload": {"value": 1}})
            assert receive_type(player_socket, "reaction_accepted")["payload"]["value"] == 1
            finished = receive_type(player_socket, "game_finished")
            assert finished["payload"]["scoreboard"][0]["score"] == 1

        stats = client.get(
            "/api/admin/meme-stats.csv",
            headers={"X-Admin-Token": settings.admin_token},
        )
        assert stats.status_code == 200
        assert "telegram_chat_id,telegram_message_id" in stats.text
        assert "-100123,1,sasha,Саша" in stats.text


def test_rejects_wrong_host_secret(tmp_path: Path, settings) -> None:
    asyncio.run(create_schema(settings))
    pack_path = tmp_path / "pack.zip"
    make_pack(pack_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        with pack_path.open("rb") as pack_file:
            response = client.post(
                "/api/host/rooms",
                data={"host_secret": "wrong", "question_grace_seconds": "5"},
                files={"pack": ("pack.zip", pack_file, "application/zip")},
            )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_host_secret"


def test_creator_can_close_current_room(tmp_path: Path, settings) -> None:
    asyncio.run(create_schema(settings))
    pack_path = tmp_path / "pack.zip"
    make_pack(pack_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        with pack_path.open("rb") as pack_file:
            created = client.post(
                "/api/host/rooms",
                data={
                    "host_secret": settings.host_secret,
                    "question_grace_seconds": "5",
                },
                files={"pack": ("pack.zip", pack_file, "application/zip")},
            )
        assert created.status_code == 200

        wrong = client.post(
            "/api/host/rooms/current/close",
            data={"host_secret": "wrong-secret"},
        )
        assert wrong.status_code == 401

        closed = client.post(
            "/api/host/rooms/current/close",
            data={"host_secret": settings.host_secret},
        )
        assert closed.status_code == 204
        snapshot = client.get(f"/api/rooms/{created.json()['room_code']}/snapshot")
        assert snapshot.json()["room"]["state"] == "CLOSED"
