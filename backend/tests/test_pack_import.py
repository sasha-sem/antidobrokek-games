from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from conftest import make_pack
from sqlalchemy import func, select

from app.core.errors import QuizError
from app.models.tables import Meme, Pack, PackStatus, Reaction, Room, RoomState
from app.services.pack_import import import_pack
from app.services.pack_validation import validate_and_extract


async def test_imports_pack_and_reuses_meme_with_reactions(
    tmp_path: Path, settings, database, storage
) -> None:
    first_zip = settings.incoming_dir / "first.zip"
    first_manifest = make_pack(first_zip)
    await import_pack(
        first_zip,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )
    old_pack_dir = settings.active_media_dir / first_manifest["pack_id"]
    assert old_pack_dir.is_dir()

    async with database.session_factory() as session, session.begin():
        meme = await session.scalar(select(Meme))
        room = Room(
            code="OLDKEK",
            pack_id=first_manifest["pack_id"],
            state=RoomState.CLOSED.value,
            host_token_hash="x" * 64,
            question_grace_seconds=5,
        )
        session.add(room)
        await session.flush()
        session.add(
            Reaction(
                meme_id=meme.id,
                identity_id=str(uuid.uuid4()),
                value=1,
                last_room_id=room.id,
            )
        )
        original_meme_id = meme.id

    second_zip = settings.incoming_dir / "second.zip"
    second_manifest = make_pack(second_zip, message_start=1)
    await import_pack(
        second_zip,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )
    async with database.session_factory() as session:
        memes = (await session.scalars(select(Meme))).all()
        reactions = await session.scalar(select(func.count(Reaction.id)))
        first_pack = await session.get(Pack, first_manifest["pack_id"])
        second_pack = await session.get(Pack, second_manifest["pack_id"])
        assert len(memes) == 1
        assert memes[0].id == original_meme_id
        assert reactions == 1
        assert first_pack.status == PackStatus.ARCHIVED.value
        assert second_pack.status == PackStatus.ACTIVE.value
    assert not old_pack_dir.exists()
    assert (settings.active_media_dir / second_manifest["pack_id"]).is_dir()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"bad_sha": True}, "sha256_mismatch"),
        ({"author_id": "unknown"}, "unknown_author"),
        ({"schema_version": 2}, "incompatible_schema"),
    ],
)
async def test_rejects_invalid_pack(tmp_path: Path, settings, kwargs: dict, code: str) -> None:
    archive = settings.incoming_dir / f"{code}.zip"
    settings.ensure_directories()
    make_pack(archive, **kwargs)
    with pytest.raises(QuizError) as caught:
        await validate_and_extract(archive, settings)
    assert caught.value.code == code


async def test_rejects_zip_slip(settings) -> None:
    settings.ensure_directories()
    archive_path = settings.incoming_dir / "slip.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.mp4", b"bad")
        archive.writestr("manifest.json", "{}")
    with pytest.raises(QuizError) as caught:
        await validate_and_extract(archive_path, settings)
    assert caught.value.code == "zip_slip"


async def test_reimports_same_active_pack(tmp_path: Path, settings, database, storage) -> None:
    template = tmp_path / "same-pack.zip"
    manifest = make_pack(template)
    first_upload = settings.incoming_dir / "same-first.zip"
    second_upload = settings.incoming_dir / "same-second.zip"
    shutil.copyfile(template, first_upload)
    shutil.copyfile(template, second_upload)

    first_id = await import_pack(
        first_upload,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )
    second_id = await import_pack(
        second_upload,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )

    assert first_id == second_id == manifest["pack_id"]
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(Pack.id))) == 1
        pack = await session.get(Pack, manifest["pack_id"])
        assert pack.status == PackStatus.ACTIVE.value
    assert (settings.active_media_dir / manifest["pack_id"]).is_dir()


async def test_reactivates_archived_pack_and_keeps_reactions(
    tmp_path: Path, settings, database, storage
) -> None:
    first_template = tmp_path / "first-template.zip"
    first_manifest = make_pack(first_template, message_start=10)
    first_upload = settings.incoming_dir / "first-upload.zip"
    shutil.copyfile(first_template, first_upload)
    await import_pack(
        first_upload,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )

    async with database.session_factory() as session, session.begin():
        meme = await session.scalar(
            select(Meme).where(Meme.telegram_message_id == 10)
        )
        room = Room(
            code="REPLAY",
            pack_id=first_manifest["pack_id"],
            state=RoomState.CLOSED.value,
            host_token_hash="x" * 64,
            question_grace_seconds=5,
        )
        session.add(room)
        await session.flush()
        session.add(
            Reaction(
                meme_id=meme.id,
                identity_id=str(uuid.uuid4()),
                value=1,
                last_room_id=room.id,
            )
        )

    second_upload = settings.incoming_dir / "second-upload.zip"
    second_manifest = make_pack(second_upload, message_start=20)
    await import_pack(
        second_upload,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )
    assert not (settings.active_media_dir / first_manifest["pack_id"]).exists()

    replay_upload = settings.incoming_dir / "replay-upload.zip"
    shutil.copyfile(first_template, replay_upload)
    replayed_id = await import_pack(
        replay_upload,
        settings=settings,
        session_factory=database.session_factory,
        storage=storage,
    )

    assert replayed_id == first_manifest["pack_id"]
    async with database.session_factory() as session:
        first_pack = await session.get(Pack, first_manifest["pack_id"])
        second_pack = await session.get(Pack, second_manifest["pack_id"])
        assert first_pack.status == PackStatus.ACTIVE.value
        assert second_pack.status == PackStatus.ARCHIVED.value
        assert await session.scalar(select(func.count(Reaction.id))) == 1
    assert (settings.active_media_dir / first_manifest["pack_id"]).is_dir()
    assert not (settings.active_media_dir / second_manifest["pack_id"]).exists()
