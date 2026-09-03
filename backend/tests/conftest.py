from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.services.media import LocalMediaStorage

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        host_secret="host-secret-for-tests",
        admin_token="admin-token-for-tests",
        data_dir=data_dir,
        database_url=f"sqlite+aiosqlite:///{data_dir / 'db' / 'quiz.sqlite3'}",
        min_questions=1,
        max_questions=50,
        question_start_delay_seconds=1,
        reveal_duration_seconds=1,
    )


@pytest.fixture
async def database(settings: Settings):
    settings.ensure_directories()
    database = Database(settings)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.close()


@pytest.fixture
def storage(settings: Settings) -> LocalMediaStorage:
    settings.ensure_directories()
    return LocalMediaStorage(settings.active_media_dir)


def make_pack(
    target: Path,
    *,
    pack_id: str | None = None,
    message_start: int = 1,
    question_count: int = 1,
    author_id: str = "sasha",
    schema_version: int = 1,
    bad_sha: bool = False,
) -> dict:
    video = FIXTURES / "sample.mp4"
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    questions = []
    filenames = []
    for index in range(question_count):
        filename = f"{uuid.uuid4()}.mp4"
        filenames.append(filename)
        questions.append(
            {
                "id": str(uuid.uuid4()),
                "position": index + 1,
                "telegram_chat_id": -100123,
                "telegram_message_id": message_start + index,
                "author_id": author_id,
                "media_path": f"videos/{filename}",
                "sha256": "0" * 64 if bad_sha else digest,
                "duration_ms": 400,
                "size_bytes": video.stat().st_size,
            }
        )
    manifest = {
        "schema_version": schema_version,
        "pack_id": pack_id or str(uuid.uuid4()),
        "title": "Тестовый пак",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authors": [
            {"id": "sasha", "display_name": "Саша"},
            {"id": "misha", "display_name": "Миша"},
        ],
        "questions": questions,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for filename in filenames:
            archive.write(video, f"videos/{filename}")
    return manifest
