from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS used_messages (
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    pack_id TEXT NOT NULL,
                    pack_title TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    UNIQUE (telegram_chat_id, telegram_message_id, pack_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def used_keys(self, chat_id: int | None = None) -> set[tuple[int, int]]:
        query = "SELECT DISTINCT telegram_chat_id, telegram_message_id FROM used_messages"
        params: tuple[int, ...] = ()
        if chat_id is not None:
            query += " WHERE telegram_chat_id = ?"
            params = (chat_id,)
        with self._connect() as connection:
            return {(int(row[0]), int(row[1])) for row in connection.execute(query, params)}

    def record(
        self,
        messages: Iterable[tuple[int, int]],
        pack_id: str,
        pack_title: str,
    ) -> None:
        used_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO used_messages (
                    telegram_chat_id, telegram_message_id, pack_id, pack_title, used_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [(chat_id, message_id, pack_id, pack_title, used_at) for chat_id, message_id in messages],
            )
