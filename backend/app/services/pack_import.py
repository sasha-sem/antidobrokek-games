from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import QuizError
from app.models.tables import Author, Meme, Pack, PackAuthor, PackItem, PackStatus, utcnow
from app.services.media import LocalMediaStorage
from app.services.pack_validation import ValidatedPack, validate_and_extract


async def _validate_existing_pack(session, manifest: dict) -> Pack | None:
    existing = await session.get(Pack, manifest["pack_id"])
    if not existing:
        return None
    if (
        existing.title != manifest["title"]
        or existing.schema_version != manifest["schema_version"]
        or existing.question_count != len(manifest["questions"])
    ):
        raise QuizError(
            "Этот pack_id уже принадлежит другому набору вопросов",
            code="pack_id_conflict",
        )
    author_ids = list(
        await session.scalars(
            select(PackAuthor.author_id)
            .where(PackAuthor.pack_id == existing.id)
            .order_by(PackAuthor.position)
        )
    )
    if author_ids != [author["id"] for author in manifest["authors"]]:
        raise QuizError(
            "Состав авторов не совпадает с ранее импортированным паком",
            code="pack_id_conflict",
        )
    rows = (
        await session.execute(
            select(PackItem, Meme)
            .join(Meme, Meme.id == PackItem.meme_id)
            .where(PackItem.pack_id == existing.id)
            .order_by(PackItem.position)
        )
    ).all()
    expected = sorted(manifest["questions"], key=lambda question: question["position"])
    actual = [
        (
            item.position,
            item.question_external_id,
            meme.telegram_chat_id,
            meme.telegram_message_id,
            meme.author_id,
        )
        for item, meme in rows
    ]
    wanted = [
        (
            question["position"],
            question["id"],
            question["telegram_chat_id"],
            question["telegram_message_id"],
            question["author_id"],
        )
        for question in expected
    ]
    if actual != wanted:
        raise QuizError(
            "Вопросы не совпадают с ранее импортированным pack_id",
            code="pack_id_conflict",
        )
    return existing


async def import_pack(
    zip_path: Path,
    *,
    settings,
    session_factory: async_sessionmaker,
    storage: LocalMediaStorage,
) -> str:
    validated: ValidatedPack | None = None
    activated = False
    pack_id = ""
    staging = f".staging-{uuid.uuid4().hex}"
    backup = f".backup-{uuid.uuid4().hex}"
    old_pack_id: str | None = None
    backup_created = False
    committed = False
    try:
        validated = await validate_and_extract(zip_path, settings)
        manifest = validated.manifest
        pack_id = manifest["pack_id"]
        async with session_factory() as session:
            await _validate_existing_pack(session, manifest)
        for video in validated.videos:
            await storage.save(video.extracted_path, f"{staging}/{video.extracted_path.name}")
        if storage.exists(pack_id):
            await storage.move(pack_id, backup)
            backup_created = True
        await storage.activate_staging(staging, pack_id)
        activated = True

        async with session_factory() as session, session.begin():
            existing_pack = await _validate_existing_pack(session, manifest)
            active = await session.scalar(select(Pack).where(Pack.status == PackStatus.ACTIVE.value))
            if active and active.id != pack_id:
                old_pack_id = active.id
                active.status = PackStatus.ARCHIVED.value
                active.archived_at = utcnow()
                await session.execute(
                    update(Meme)
                    .where(
                        Meme.id.in_(
                            select(PackItem.meme_id).where(PackItem.pack_id == active.id)
                        )
                    )
                    .values(media_path=None, updated_at=utcnow())
                )
                await session.flush()

            for item in manifest["authors"]:
                author = await session.get(Author, item["id"])
                if author:
                    author.display_name = item["display_name"]
                else:
                    session.add(Author(id=item["id"], display_name=item["display_name"]))
            await session.flush()

            created_at = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
            if existing_pack:
                existing_pack.status = PackStatus.ACTIVE.value
                existing_pack.activated_at = utcnow()
                existing_pack.archived_at = None
            else:
                session.add(
                    Pack(
                        id=pack_id,
                        title=manifest["title"],
                        schema_version=manifest["schema_version"],
                        status=PackStatus.ACTIVE.value,
                        question_count=len(manifest["questions"]),
                        created_at=created_at,
                        activated_at=utcnow(),
                    )
                )
            await session.flush()
            if not existing_pack:
                session.add_all(
                    [
                        PackAuthor(pack_id=pack_id, author_id=item["id"], position=position)
                        for position, item in enumerate(manifest["authors"], start=1)
                    ]
                )
            for video in validated.videos:
                question = video.question
                meme = await session.scalar(
                    select(Meme).where(
                        Meme.telegram_chat_id == question["telegram_chat_id"],
                        Meme.telegram_message_id == question["telegram_message_id"],
                    )
                )
                relative_path = f"{pack_id}/{video.extracted_path.name}"
                if meme:
                    if meme.author_id != question["author_id"]:
                        raise QuizError(
                            "Автор повторного Telegram-сообщения не совпадает с историей",
                            code="author_mismatch",
                        )
                    meme.content_hash = question["sha256"]
                    meme.media_path = relative_path
                    meme.duration_ms = question["duration_ms"]
                    meme.updated_at = utcnow()
                else:
                    meme = Meme(
                        telegram_chat_id=question["telegram_chat_id"],
                        telegram_message_id=question["telegram_message_id"],
                        author_id=question["author_id"],
                        content_hash=question["sha256"],
                        media_path=relative_path,
                        duration_ms=question["duration_ms"],
                    )
                    session.add(meme)
                await session.flush()
                if not existing_pack:
                    session.add(
                        PackItem(
                            pack_id=pack_id,
                            meme_id=meme.id,
                            position=question["position"],
                            question_external_id=question["id"],
                        )
                    )
        committed = True
        if backup_created:
            await storage.delete(backup)
        if old_pack_id and old_pack_id != pack_id:
            await storage.delete(old_pack_id)
        return pack_id
    except Exception:
        if activated and pack_id and not committed:
            await storage.delete(pack_id)
            if backup_created:
                await storage.move(backup, pack_id)
        elif not activated:
            await storage.delete(staging)
            if backup_created:
                await storage.move(backup, pack_id)
        raise
    finally:
        zip_path.unlink(missing_ok=True)
        if validated:
            await asyncio.to_thread(shutil.rmtree, validated.extraction_dir, True)
