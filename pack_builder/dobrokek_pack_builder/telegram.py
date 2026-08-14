from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .authors import AuthorCatalog, extract_author_name
from .models import ScanResult, TelegramVideo


class TelegramSource:
    """Thin Telethon adapter. The server side never imports or uses this class."""

    def __init__(self, api_id: int, api_hash: str, session_path: Path):
        try:
            from telethon import TelegramClient
        except ImportError as exc:  # pragma: no cover - dependency error is user-facing
            raise RuntimeError("Telethon не установлен: выполните pip install -e .") from exc
        session_path.parent.mkdir(parents=True, exist_ok=True)
        self.client = TelegramClient(str(session_path), api_id, api_hash)

    async def __aenter__(self) -> TelegramSource:
        await self.client.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.disconnect()

    @staticmethod
    def _is_video(message: Any) -> bool:
        if getattr(message, "video", None) is not None:
            return True
        document = getattr(message, "document", None)
        mime_type = getattr(document, "mime_type", "") if document else ""
        return bool(mime_type and mime_type.startswith("video/"))

    @staticmethod
    def _video_metadata(message: Any) -> tuple[float, int]:
        document = getattr(message, "document", None)
        size = int(getattr(document, "size", 0) or 0)
        duration = 0.0
        for attribute in getattr(document, "attributes", ()) or ():
            value = getattr(attribute, "duration", None)
            if value is not None:
                duration = float(value)
                break
        return duration, size

    async def scan(
        self,
        channel: int | str,
        catalog: AuthorCatalog,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> ScanResult:
        total = 0
        videos: list[TelegramVideo] = []
        entity = await self.client.get_entity(channel)
        async for message in self.client.iter_messages(entity):
            total += 1
            date = message.date
            comparable = date.replace(tzinfo=None) if date.tzinfo else date
            if from_date and comparable < from_date:
                continue
            if to_date and comparable >= to_date:
                continue
            if not self._is_video(message):
                continue
            entity_texts = message.get_entities_text() if hasattr(message, "get_entities_text") else None
            raw_author = extract_author_name(
                getattr(message, "raw_text", None),
                getattr(message, "entities", None),
                entity_texts,
            )
            author = catalog.resolve(raw_author)
            duration, size = self._video_metadata(message)
            videos.append(
                TelegramVideo(
                    chat_id=int(getattr(message, "chat_id", channel)),
                    message_id=int(message.id),
                    date=date,
                    duration_seconds=duration,
                    size_bytes=size,
                    author_id=author.id if author else None,
                    raw_author=raw_author,
                    message=message,
                )
            )
        return ScanResult(total_messages=total, videos=tuple(videos))

    async def download(self, video: TelegramVideo, target: Path) -> Path:
        downloaded = await self.client.download_media(video.message, file=str(target))
        if not downloaded:
            raise RuntimeError(f"Telegram не вернул файл для сообщения {video.message_id}")
        return Path(downloaded)
