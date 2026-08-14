"""Initial quiz schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "memes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("telegram_chat_id", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.String(64), sa.ForeignKey("authors.id"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("media_path", sa.String(160), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("telegram_chat_id", "telegram_message_id"),
    )
    op.create_table(
        "packs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_packs_one_active",
        "packs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "pack_authors",
        sa.Column("pack_id", sa.String(36), sa.ForeignKey("packs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("author_id", sa.String(64), sa.ForeignKey("authors.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "pack_items",
        sa.Column("pack_id", sa.String(36), sa.ForeignKey("packs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("meme_id", sa.String(36), sa.ForeignKey("memes.id"), nullable=False),
        sa.Column("question_external_id", sa.String(36), nullable=False),
        sa.UniqueConstraint("pack_id", "meme_id"),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(6), nullable=False, unique=True),
        sa.Column("pack_id", sa.String(36), sa.ForeignKey("packs.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("current_position", sa.Integer(), nullable=True),
        sa.Column("host_token_hash", sa.String(64), nullable=False),
        sa.Column("question_grace_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "players",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_id", sa.String(36), nullable=False),
        sa.Column("display_name", sa.String(24), nullable=False),
        sa.Column("display_name_normalized", sa.String(24), nullable=False),
        sa.Column("reconnect_token_hash", sa.String(64), nullable=False),
        sa.Column("is_connected", sa.Boolean(), nullable=False),
        sa.Column("is_ready", sa.Boolean(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("room_id", "identity_id"),
        sa.UniqueConstraint("room_id", "display_name_normalized", name="uq_players_room_name_ci"),
    )
    op.create_table(
        "question_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meme_id", sa.String(36), sa.ForeignKey("memes.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("revealed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("room_id", "position"),
    )
    op.create_table(
        "answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question_run_id", sa.String(36), sa.ForeignKey("question_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.String(36), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("selected_author_id", sa.String(64), sa.ForeignKey("authors.id"), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("question_run_id", "player_id"),
    )
    op.create_table(
        "reactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meme_id", sa.String(36), sa.ForeignKey("memes.id"), nullable=False),
        sa.Column("identity_id", sa.String(36), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("last_room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=False),
        *timestamps(),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_reactions_value"),
        sa.UniqueConstraint("meme_id", "identity_id"),
    )


def downgrade() -> None:
    tables = (
        "reactions",
        "answers",
        "question_runs",
        "players",
        "rooms",
        "pack_items",
        "pack_authors",
        "packs",
        "memes",
        "authors",
    )
    for table in tables:
        op.drop_table(table)
