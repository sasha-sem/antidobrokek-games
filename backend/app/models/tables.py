from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def uuid_string() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PackStatus(enum.StrEnum):
    IMPORTING = "IMPORTING"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class RoomState(enum.StrEnum):
    LOBBY = "LOBBY"
    PRELOADING = "PRELOADING"
    QUESTION = "QUESTION"
    REVEAL = "REVEAL"
    FINISHED = "FINISHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Author(Base, TimestampMixin):
    __tablename__ = "authors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)


class Meme(Base, TimestampMixin):
    __tablename__ = "memes"
    __table_args__ = (UniqueConstraint("telegram_chat_id", "telegram_message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    telegram_chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    media_path: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


Index(
    "uq_packs_one_active",
    Pack.status,
    unique=True,
    sqlite_where=Pack.status == PackStatus.ACTIVE.value,
)


class PackItem(Base):
    __tablename__ = "pack_items"
    __table_args__ = (
        UniqueConstraint("pack_id", "meme_id"),
    )

    pack_id: Mapped[str] = mapped_column(
        ForeignKey("packs.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    meme_id: Mapped[str] = mapped_column(ForeignKey("memes.id"), nullable=False)
    question_external_id: Mapped[str] = mapped_column(String(36), nullable=False)


class PackAuthor(Base):
    __tablename__ = "pack_authors"

    pack_id: Mapped[str] = mapped_column(
        ForeignKey("packs.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    pack_id: Mapped[str] = mapped_column(ForeignKey("packs.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=RoomState.LOBBY.value)
    current_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question_grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("room_id", "identity_id"),
        UniqueConstraint("room_id", "display_name_normalized", name="uq_players_room_name_ci"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    display_name: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name_normalized: Mapped[str] = mapped_column(String(24), nullable=False)
    reconnect_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class QuestionRun(Base):
    __tablename__ = "question_runs"
    __table_args__ = (UniqueConstraint("room_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    meme_id: Mapped[str] = mapped_column(ForeignKey("memes.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Answer(Base, TimestampMixin):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("question_run_id", "player_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    question_run_id: Mapped[str] = mapped_column(
        ForeignKey("question_runs.id", ondelete="CASCADE"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    selected_author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Reaction(Base, TimestampMixin):
    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("meme_id", "identity_id"),
        CheckConstraint("value IN (-1, 1)", name="ck_reactions_value"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    meme_id: Mapped[str] = mapped_column(ForeignKey("memes.id"), nullable=False)
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    last_room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), nullable=False)
