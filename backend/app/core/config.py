from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    domain: str = "localhost"
    host_secret: str = Field(default="change-me-host-secret", min_length=16)
    admin_token: str = Field(default="change-me-admin-token", min_length=16)
    database_url: str = "sqlite+aiosqlite:////data/quiz/db/dobrokek.sqlite3"
    data_dir: Path = Path("/data/quiz")
    max_players: int = Field(default=5, ge=1, le=5)
    max_pack_size_mb: int = Field(default=500, ge=1)
    max_video_size_mb: int = Field(default=50, ge=1)
    max_video_duration_seconds: int = Field(default=60, ge=1, le=600)
    max_questions: int = Field(default=50, ge=1, le=50)
    min_questions: int = Field(default=5, ge=1, le=50)
    preload_timeout_seconds: int = Field(default=15, ge=1, le=120)
    reveal_duration_seconds: int = Field(default=10, ge=1, le=60)
    default_question_grace_seconds: int = Field(default=5, ge=0, le=60)
    question_start_delay_seconds: float = Field(default=1.5, ge=1, le=2)
    ffprobe_binary: str = "ffprobe"
    public_media_prefix: str = "/media"
    cors_origins: str = ""

    @field_validator("host_secret", "admin_token")
    @classmethod
    def reject_placeholder_in_production(cls, value: str) -> str:
        if len(value.encode()) < 16:
            raise ValueError("Секрет должен быть не короче 16 байт")
        return value

    @property
    def database_path(self) -> Path:
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("MVP поддерживает только sqlite+aiosqlite")
        return Path(self.database_url.removeprefix(prefix))

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def active_media_dir(self) -> Path:
        return self.data_dir / "media" / "active"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        for path in (
            self.database_path.parent,
            self.incoming_dir,
            self.active_media_dir,
            self.data_dir / "backups",
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
