from __future__ import annotations

import asyncio
import hashlib
import json
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.core.config import Settings
from app.core.errors import QuizError


@dataclass(frozen=True, slots=True)
class ValidatedVideo:
    question: dict[str, Any]
    extracted_path: Path


@dataclass(frozen=True, slots=True)
class ValidatedPack:
    manifest: dict[str, Any]
    videos: tuple[ValidatedVideo, ...]
    extraction_dir: Path


def shared_schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "shared" / "pack-schema.json"


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    unix_mode = info.external_attr >> 16
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise QuizError(f"Небезопасный путь в ZIP: {info.filename}", code="zip_slip")
    if stat.S_ISLNK(unix_mode):
        raise QuizError("Символические ссылки в ZIP запрещены", code="zip_symlink")
    if not info.is_dir() and path.name != "manifest.json" and path.suffix.lower() != ".mp4":
        raise QuizError(f"Запрещённый тип файла в ZIP: {info.filename}", code="zip_file_type")
    if info.is_dir() and path.parts not in (("videos",),):
        raise QuizError(f"Неизвестный каталог в ZIP: {info.filename}", code="invalid_archive_contents")
    return path


def _schema_validate(manifest: dict[str, Any]) -> None:
    schema = json.loads(shared_schema_path().read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(map(str, first.absolute_path)) or "$"
        code = "incompatible_schema" if location == "schema_version" else "invalid_manifest"
        raise QuizError(f"Некорректный manifest ({location}): {first.message}", code=code)
    author_ids = [author["id"] for author in manifest["authors"]]
    if len(author_ids) != len(set(author_ids)):
        raise QuizError("В manifest повторяются авторы", code="invalid_manifest")
    known_authors = set(author_ids)
    positions: set[int] = set()
    sources: set[tuple[int, int]] = set()
    media_paths: set[str] = set()
    for question in manifest["questions"]:
        if question["author_id"] not in known_authors:
            raise QuizError(f"Неизвестный author_id: {question['author_id']}", code="unknown_author")
        position = question["position"]
        source = (question["telegram_chat_id"], question["telegram_message_id"])
        media_path = PurePosixPath(question["media_path"])
        try:
            uuid.UUID(media_path.stem, version=4)
        except ValueError as exc:
            raise QuizError("Имя видео должно быть UUID v4", code="invalid_manifest") from exc
        if position in positions or source in sources or question["media_path"] in media_paths:
            raise QuizError("В manifest есть повторяющиеся вопросы", code="invalid_manifest")
        positions.add(position)
        sources.add(source)
        media_paths.add(question["media_path"])
    if positions != set(range(1, len(positions) + 1)):
        raise QuizError("Позиции вопросов должны идти с 1 без пропусков", code="invalid_manifest")


async def _probe(path: Path, settings: Settings) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        settings.ffprobe_binary,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise QuizError(f"FFprobe не смог прочитать {path.name}: {stderr.decode()[-300:]}", code="invalid_video")
    return json.loads(stdout)


def _fps(value: str) -> float:
    left, _, right = value.partition("/")
    denominator = float(right or 1)
    return float(left or 0) / denominator if denominator else 0


async def _validate_video(path: Path, question: dict[str, Any], settings: Settings) -> None:
    if path.stat().st_size != question["size_bytes"]:
        raise QuizError(f"Размер {path.name} не совпадает с manifest", code="size_mismatch")
    if path.stat().st_size > settings.max_video_size_mb * 1024 * 1024:
        raise QuizError(f"Видео {path.name} превышает лимит", code="video_too_large")
    payload = await _probe(path, settings)
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise QuizError(f"Видео {path.name} должно быть H.264/yuv420p", code="invalid_video")
    if int(video.get("width") or 0) > 1280 or int(video.get("height") or 0) > 720:
        raise QuizError(f"Разрешение {path.name} выше 1280x720", code="invalid_video")
    if _fps(str(video.get("avg_frame_rate") or "0/1")) > 30.05:
        raise QuizError(f"FPS {path.name} выше 30", code="invalid_video")
    if audio and audio.get("codec_name") != "aac":
        raise QuizError(f"Аудио {path.name} должно быть AAC", code="invalid_video")
    duration_ms = round(float(payload.get("format", {}).get("duration") or 0) * 1000)
    if abs(duration_ms - question["duration_ms"]) > 500:
        raise QuizError(f"Длительность {path.name} не совпадает с manifest", code="duration_mismatch")
    if duration_ms > settings.max_video_duration_seconds * 1000 + 250:
        raise QuizError(
            f"Видео {path.name} длиннее {settings.max_video_duration_seconds} секунд",
            code="video_too_long",
        )


async def validate_and_extract(zip_path: Path, settings: Settings) -> ValidatedPack:
    extraction_dir = settings.incoming_dir / f"extract-{uuid.uuid4().hex}"
    extraction_dir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            for info in infos:
                _safe_member(info)
            files = {info.filename: info for info in infos if not info.is_dir()}
            if "manifest.json" not in files or files["manifest.json"].file_size > 1024 * 1024:
                raise QuizError("ZIP не содержит корректный manifest.json", code="missing_manifest")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise QuizError("manifest.json не является корректным UTF-8 JSON", code="invalid_manifest") from exc
            _schema_validate(manifest)
            questions = manifest["questions"]
            if not settings.min_questions <= len(questions) <= settings.max_questions:
                raise QuizError(
                    f"В паке должно быть от {settings.min_questions} до {settings.max_questions} вопросов",
                    code="question_count",
                )
            expected_paths = {question["media_path"] for question in questions}
            actual_paths = set(files) - {"manifest.json"}
            if actual_paths != expected_paths:
                raise QuizError("Список видео в ZIP не совпадает с manifest", code="invalid_archive_contents")
            total_uncompressed = sum(files[path].file_size for path in expected_paths)
            free = __import__("shutil").disk_usage(settings.data_dir).free
            if free < total_uncompressed * 2 + 64 * 1024 * 1024:
                raise QuizError("На диске недостаточно места для импорта", code="insufficient_disk", status_code=507)
            validated: list[ValidatedVideo] = []
            for question in questions:
                info = files[question["media_path"]]
                target = extraction_dir / PurePosixPath(question["media_path"]).name
                digest = hashlib.sha256()
                with archive.open(info) as source, target.open("wb") as destination:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        destination.write(chunk)
                if digest.hexdigest() != question["sha256"]:
                    raise QuizError(f"SHA-256 не совпадает для {target.name}", code="sha256_mismatch")
                await _validate_video(target, question, settings)
                validated.append(ValidatedVideo(question, target))
        return ValidatedPack(manifest, tuple(validated), extraction_dir)
    except Exception:
        await asyncio.to_thread(__import__("shutil").rmtree, extraction_dir, True)
        raise
