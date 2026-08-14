from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Author:
    id: str
    display_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TelegramVideo:
    chat_id: int
    message_id: int
    date: datetime
    duration_seconds: float
    size_bytes: int
    author_id: str | None
    raw_author: str | None
    message: object | None = None


@dataclass(frozen=True, slots=True)
class ScanResult:
    total_messages: int
    videos: tuple[TelegramVideo, ...]

    @property
    def recognized(self) -> tuple[TelegramVideo, ...]:
        return tuple(video for video in self.videos if video.author_id is not None)

    @property
    def unknown(self) -> tuple[TelegramVideo, ...]:
        return tuple(video for video in self.videos if video.author_id is None)
