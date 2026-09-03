from __future__ import annotations

import json
import os
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .authors import AuthorCatalog
from .history import HistoryStore
from .manifest import sha256_file, validate_manifest
from .models import ScanResult, TelegramVideo
from .selection import distribution, select_balanced, select_random
from .telegram import TelegramSource
from .video import transcode_video


class PackBuildError(RuntimeError):
    pass


def eligible_videos(
    scan: ScanResult,
    *,
    history: HistoryStore,
    max_duration_seconds: float,
    allow_reuse: bool,
) -> list[TelegramVideo]:
    used = history.used_keys()
    return [
        video
        for video in scan.recognized
        if 0 < video.duration_seconds <= max_duration_seconds
        and (allow_reuse or (video.chat_id, video.message_id) not in used)
    ]


async def build_pack(
    source: TelegramSource,
    scan: ScanResult,
    catalog: AuthorCatalog,
    history: HistoryStore,
    *,
    count: int,
    title: str,
    output: Path,
    max_duration_seconds: float,
    max_file_size_bytes: int,
    allow_reuse: bool,
    allow_imbalance: bool,
    selection: str,
    skip_unknown_authors: bool,
    seed: int | str | None,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    if scan.unknown and not skip_unknown_authors:
        unknown = sorted({video.raw_author or "<подпись не найдена>" for video in scan.unknown})
        raise PackBuildError(
            f"Найдено {len(scan.unknown)} видео с неизвестными авторами: {', '.join(unknown)}. "
            "Добавьте aliases или используйте --skip-unknown-authors."
        )
    candidates = eligible_videos(
        scan,
        history=history,
        max_duration_seconds=max_duration_seconds,
        allow_reuse=allow_reuse,
    )
    if selection == "random":
        selected = select_random(candidates, count, seed=seed)
    elif selection == "balanced":
        selected = select_balanced(
            candidates,
            count,
            seed=seed,
            allow_imbalance=allow_imbalance,
        )
    else:
        raise PackBuildError(f"Неизвестный режим выбора: {selection}")
    pack_id = str(uuid.uuid4())
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pack_id": pack_id,
        "title": title.strip(),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authors": [
            {"id": author.id, "display_name": author.display_name} for author in catalog.authors
        ],
        "questions": [],
    }
    final_tmp = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tempfile.TemporaryDirectory(prefix="dobrokek-pack-") as temp_name:
            temp_dir = Path(temp_name)
            videos_dir = temp_dir / "videos"
            downloads_dir = temp_dir / "downloads"
            videos_dir.mkdir()
            downloads_dir.mkdir()
            for position, video in enumerate(selected, start=1):
                media_id = str(uuid.uuid4())
                source_path = await source.download(video, downloads_dir / f"source-{position}")
                target_path = videos_dir / f"{media_id}.mp4"
                probe = transcode_video(
                    source_path,
                    target_path,
                    ffmpeg_binary=ffmpeg_binary,
                    ffprobe_binary=ffprobe_binary,
                    max_duration_seconds=max_duration_seconds,
                    max_size_bytes=max_file_size_bytes,
                )
                manifest["questions"].append(
                    {
                        "id": str(uuid.uuid4()),
                        "position": position,
                        "telegram_chat_id": video.chat_id,
                        "telegram_message_id": video.message_id,
                        "author_id": video.author_id,
                        "media_path": f"videos/{target_path.name}",
                        "sha256": sha256_file(target_path),
                        "duration_ms": probe.duration_ms,
                        "size_bytes": probe.size_bytes,
                    }
                )
                source_path.unlink(missing_ok=True)
            validate_manifest(manifest)
            manifest_path = temp_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with zipfile.ZipFile(final_tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(manifest_path, "manifest.json")
                for media in sorted(videos_dir.iterdir()):
                    archive.write(media, f"videos/{media.name}")
        os.replace(final_tmp, output)
        try:
            history.record(
                ((video.chat_id, video.message_id) for video in selected), pack_id, title
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
    finally:
        final_tmp.unlink(missing_ok=True)
    return manifest, distribution(selected)
