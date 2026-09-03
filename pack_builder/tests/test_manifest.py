import hashlib
import uuid
from pathlib import Path, PureWindowsPath

import pytest

from dobrokek_pack_builder.manifest import safe_media_path, sha256_file, validate_manifest


def make_manifest() -> dict:
    return {
        "schema_version": 1,
        "pack_id": str(uuid.uuid4()),
        "title": "Test",
        "created_at": "2026-08-13T18:30:00Z",
        "authors": [
            {"id": "sasha", "display_name": "Саша"},
            {"id": "misha", "display_name": "Миша"},
        ],
        "questions": [
            {
                "id": str(uuid.uuid4()),
                "position": 1,
                "telegram_chat_id": -100123,
                "telegram_message_id": 42,
                "author_id": "sasha",
                "media_path": f"videos/{uuid.uuid4()}.mp4",
                "sha256": "a" * 64,
                "duration_ms": 1200,
                "size_bytes": 123,
            }
        ],
    }


def test_manifest_and_sha256(tmp_path: Path) -> None:
    manifest = make_manifest()
    validate_manifest(manifest)
    path = tmp_path / "file.bin"
    path.write_bytes(b"dobrokek")
    assert sha256_file(path) == hashlib.sha256(b"dobrokek").hexdigest()


def test_unknown_author_and_unsafe_path_are_rejected() -> None:
    manifest = make_manifest()
    manifest["questions"][0]["author_id"] = "unknown"
    with pytest.raises(ValueError, match="author_id"):
        validate_manifest(manifest)
    assert not safe_media_path("videos/../secret.mp4")
    assert not safe_media_path(str(PureWindowsPath("videos", "file.mp4")))
    assert safe_media_path(f"videos/{uuid.uuid4()}.mp4")


def test_manifest_accepts_up_to_50_questions() -> None:
    manifest = make_manifest()
    template = manifest["questions"][0]
    manifest["questions"] = [
        {
            **template,
            "id": str(uuid.uuid4()),
            "position": position,
            "telegram_message_id": position,
            "media_path": f"videos/{uuid.uuid4()}.mp4",
        }
        for position in range(1, 51)
    ]

    validate_manifest(manifest)

    manifest["questions"].append(
        {
            **template,
            "id": str(uuid.uuid4()),
            "position": 51,
            "telegram_message_id": 51,
            "media_path": f"videos/{uuid.uuid4()}.mp4",
        }
    )
    with pytest.raises(ValueError, match="too long"):
        validate_manifest(manifest)
