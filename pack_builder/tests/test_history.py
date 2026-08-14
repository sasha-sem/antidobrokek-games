from datetime import UTC, datetime
from pathlib import Path

from dobrokek_pack_builder.builder import eligible_videos
from dobrokek_pack_builder.history import HistoryStore
from dobrokek_pack_builder.models import ScanResult, TelegramVideo


def test_used_messages_are_excluded(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.record([(-100, 1)], "pack", "Pack")
    scan = ScanResult(
        2,
        (
            TelegramVideo(-100, 1, datetime.now(UTC), 5, 1, "a", "A"),
            TelegramVideo(-100, 2, datetime.now(UTC), 5, 1, "a", "A"),
        ),
    )
    selected = eligible_videos(scan, history=history, max_duration_seconds=60, allow_reuse=False)
    assert [video.message_id for video in selected] == [2]
    assert len(eligible_videos(scan, history=history, max_duration_seconds=60, allow_reuse=True)) == 2
