from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import QuizError
from app.db.session import Database
from app.services.game import GameService
from app.services.media import LocalMediaStorage
from app.services.stats import StatsService
from app.websocket.manager import ConnectionManager

logger = logging.getLogger("dobrokek.quiz")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_directories()
        database = Database(settings)
        storage = LocalMediaStorage(settings.active_media_dir, settings.public_media_prefix)
        game = GameService(database.session_factory, settings, storage)
        app.state.settings = settings
        app.state.database = database
        app.state.storage = storage
        app.state.game = game
        app.state.stats = StatsService(database.session_factory)
        app.state.connections = ConnectionManager(game)
        app.state.import_lock = asyncio.Lock()
        await app.state.connections.recover()
        yield
        await app.state.connections.shutdown()
        await database.close()

    app = FastAPI(title="Доброкек Quiz API", version="0.1.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)

    @app.exception_handler(QuizError)
    async def quiz_error_handler(_: Request, exc: QuizError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def unknown_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера"}},
        )

    @app.websocket("/ws/rooms/{code}")
    async def room_websocket(socket: WebSocket, code: str) -> None:
        await socket.accept()
        manager: ConnectionManager = socket.app.state.connections
        room = None
        role = ""
        player_id = None
        try:
            raw = await asyncio.wait_for(socket.receive_text(), timeout=10)
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise QuizError("Первое WebSocket-сообщение должно быть JSON", code="authentication_required") from exc
            if message.get("type") != "authenticate":
                raise QuizError("Сначала нужно аутентифицироваться", code="authentication_required")
            payload = message.get("payload") or {}
            role = str(payload.get("role", ""))
            room, player = await socket.app.state.game.authenticate(
                code.upper(), role, str(payload.get("token", ""))
            )
            player_id = player.id if player else None
            await manager.register(socket, room, role, player_id)
            await manager.authenticated_snapshot(socket, room, role, player_id)
            while True:
                message = await socket.receive_json()
                try:
                    await manager.handle(socket, room, role, player_id, message)
                except QuizError as exc:
                    await manager.send(
                        socket,
                        "error",
                        {"code": exc.code, "message": exc.message},
                        message.get("request_id"),
                    )
        except (TimeoutError, WebSocketDisconnect):
            pass
        except QuizError as exc:
            await manager.send(socket, "error", {"code": exc.code, "message": exc.message})
            await socket.close(code=4003 if exc.status_code in (401, 403) else 4000)
        except Exception:
            logger.exception("Unhandled WebSocket error")
            try:
                await manager.send(socket, "error", {"code": "internal_error", "message": "Ошибка сервера"})
                await socket.close(code=1011)
            except Exception:
                pass
        finally:
            if room:
                await manager.unregister(socket, room, role, player_id)

    return app


app = create_app()
