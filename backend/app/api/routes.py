from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text

from app.core.errors import QuizError
from app.core.security import verify_secret
from app.models.tables import Room
from app.schemas.rest import HostRoomResponse, JoinRequest, JoinResponse
from app.services.game import OPEN_ROOM_STATES
from app.services.pack_import import import_pack

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict:
    async with request.app.state.database.session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


async def _save_upload(upload: UploadFile, target: Path, max_bytes: int) -> int:
    size = 0
    try:
        with target.open("xb") as destination:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise QuizError("Размер ZIP превышает лимит", code="pack_too_large", status_code=413)
                destination.write(chunk)
        if size == 0:
            raise QuizError("Загружен пустой файл", code="empty_pack")
        return size
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


@router.post("/host/rooms", response_model=HostRoomResponse)
async def create_host_room(
    request: Request,
    host_secret: str = Form(...),
    pack: UploadFile = File(...),
    question_grace_seconds: int = Form(...),
) -> HostRoomResponse:
    settings = request.app.state.settings
    if not verify_secret(host_secret, settings.host_secret):
        raise QuizError("Неверный секрет ведущего", code="invalid_host_secret", status_code=401)
    if not pack.filename or Path(pack.filename).suffix.lower() != ".zip":
        raise QuizError("Нужен ZIP-файл пака", code="invalid_archive")
    if not 0 <= question_grace_seconds <= 60:
        raise QuizError("Дополнительное время должно быть от 0 до 60 секунд")
    async with request.app.state.import_lock:
        async with request.app.state.database.session_factory() as session:
            if await session.scalar(select(Room.id).where(Room.state.in_(OPEN_ROOM_STATES))):
                raise QuizError("Сначала закройте текущую комнату", code="active_room_exists", status_code=409)
        free = shutil.disk_usage(settings.data_dir).free
        if free < 64 * 1024 * 1024:
            raise QuizError("На диске недостаточно места", code="insufficient_disk", status_code=507)
        incoming = settings.incoming_dir / f"upload-{uuid.uuid4().hex}.zip"
        await _save_upload(pack, incoming, settings.max_pack_size_mb * 1024 * 1024)
        pack_id = await import_pack(
            incoming,
            settings=settings,
            session_factory=request.app.state.database.session_factory,
            storage=request.app.state.storage,
        )
        room, token = await request.app.state.game.create_room(pack_id, question_grace_seconds)
    return HostRoomResponse(
        room_code=room.code,
        host_token=token,
        host_url=f"/host/{room.code}",
        player_url=f"/room/{room.code}",
    )


@router.post("/host/rooms/current/close", status_code=204)
async def close_current_room(
    request: Request,
    host_secret: str = Form(...),
) -> None:
    if not verify_secret(host_secret, request.app.state.settings.host_secret):
        raise QuizError("Неверный секрет создания игры", code="invalid_host_secret", status_code=401)
    async with request.app.state.database.session_factory() as session:
        room = await session.scalar(
            select(Room)
            .where(Room.state.in_(OPEN_ROOM_STATES))
            .order_by(Room.created_at.desc())
        )
    if not room:
        raise QuizError("Нет открытой комнаты", code="no_active_room", status_code=404)
    await request.app.state.game.close(room.id)
    await request.app.state.connections.broadcast(
        room.id,
        "room_state_changed",
        {"state": "CLOSED"},
    )
    await request.app.state.connections.close_room(
        room.id,
        4000,
        "Комната закрыта создателем",
    )


@router.post("/rooms/{code}/join", response_model=JoinResponse)
async def join_room(code: str, payload: JoinRequest, request: Request) -> JoinResponse:
    player, token = await request.app.state.game.join(
        code.upper(), payload.display_name, str(payload.identity_id)
    )
    return JoinResponse(player_id=player.id, reconnect_token=token)


@router.get("/rooms/{code}/snapshot")
async def public_snapshot(code: str, request: Request) -> dict:
    return await request.app.state.game.public_snapshot(code.upper())


@router.post("/rooms/{code}/leave", status_code=204)
async def leave_room(
    code: str,
    request: Request,
    reconnect_token: str = Header(..., alias="X-Reconnect-Token"),
) -> None:
    await request.app.state.game.leave(code.upper(), reconnect_token)


async def _stats_rows(
    request: Request,
    admin_token: str,
    min_votes: int,
    author_id: str | None,
    sort: str,
    order: str,
) -> list[dict]:
    if not verify_secret(admin_token, request.app.state.settings.admin_token):
        raise QuizError("Неверный admin token", code="unauthorized", status_code=401)
    return await request.app.state.stats.rows(
        min_votes=min_votes, author_id=author_id, sort=sort, order=order
    )


@router.get("/admin/meme-stats.json")
async def stats_json(
    request: Request,
    admin_token: str = Header(..., alias="X-Admin-Token"),
    min_votes: int = Query(default=0, ge=0),
    author_id: str | None = None,
    sort: str = "rating",
    order: str = "desc",
) -> list[dict]:
    return await _stats_rows(request, admin_token, min_votes, author_id, sort, order)


@router.get("/admin/meme-stats.csv", response_class=PlainTextResponse)
async def stats_csv(
    request: Request,
    admin_token: str = Header(..., alias="X-Admin-Token"),
    min_votes: int = Query(default=0, ge=0),
    author_id: str | None = None,
    sort: str = "rating",
    order: str = "desc",
) -> PlainTextResponse:
    rows = await _stats_rows(request, admin_token, min_votes, author_id, sort, order)
    return PlainTextResponse(
        request.app.state.stats.csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dobrokek-meme-stats.csv"'},
    )
