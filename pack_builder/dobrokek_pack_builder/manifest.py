from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def shared_schema_path() -> Path:
    repository_schema = Path(__file__).resolve().parents[2] / "shared" / "pack-schema.json"
    return repository_schema if repository_schema.is_file() else Path(__file__).with_name("pack-schema.json")


def load_schema() -> dict[str, Any]:
    return json.loads(shared_schema_path().read_text(encoding="utf-8"))


def safe_media_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and len(path.parts) == 2
        and path.parts[0] == "videos"
        and ".." not in path.parts
        and path.suffix == ".mp4"
    )


def validate_manifest(manifest: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(load_schema(), format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(f"{'/'.join(map(str, error.path)) or '$'}: {error.message}" for error in errors)
        raise ValueError(f"Манифест не соответствует JSON Schema: {details}")
    author_ids = [author["id"] for author in manifest["authors"]]
    if len(author_ids) != len(set(author_ids)):
        raise ValueError("В manifest повторяются id авторов")
    known = set(author_ids)
    positions = [question["position"] for question in manifest["questions"]]
    if sorted(positions) != list(range(1, len(positions) + 1)):
        raise ValueError("Позиции вопросов должны идти подряд с 1")
    sources: set[tuple[int, int]] = set()
    question_ids: set[str] = set()
    media_paths: set[str] = set()
    for question in manifest["questions"]:
        if question["author_id"] not in known:
            raise ValueError(f"Неизвестный author_id: {question['author_id']}")
        source = (question["telegram_chat_id"], question["telegram_message_id"])
        if source in sources:
            raise ValueError(f"Повтор Telegram-сообщения: {source}")
        if question["id"] in question_ids:
            raise ValueError(f"Повтор id вопроса: {question['id']}")
        if question["media_path"] in media_paths or not safe_media_path(question["media_path"]):
            raise ValueError(f"Недопустимый или повторный media_path: {question['media_path']}")
        sources.add(source)
        question_ids.add(question["id"])
        media_paths.add(question["media_path"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
