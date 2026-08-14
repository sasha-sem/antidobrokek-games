from datetime import UTC, datetime

import pytest

from dobrokek_pack_builder.models import TelegramVideo
from dobrokek_pack_builder.selection import SelectionError, distribution, select_balanced


def video(author: str, message_id: int) -> TelegramVideo:
    return TelegramVideo(-1001, message_id, datetime.now(UTC), 3, 100, author, author)


def test_balanced_selection_and_seed_are_reproducible() -> None:
    videos = [video(author, index) for author in ("a", "b", "c") for index in range(10)]
    first = select_balanced(videos, 8, seed="stable", allow_imbalance=False)
    second = select_balanced(videos, 8, seed="stable", allow_imbalance=False)
    assert [item.message_id for item in first] == [item.message_id for item in second]
    assert max(distribution(first).values()) - min(distribution(first).values()) <= 1


def test_imbalance_requires_flag() -> None:
    videos = [video("a", index) for index in range(10)] + [video("b", 99)]
    with pytest.raises(SelectionError, match="allow-imbalance"):
        select_balanced(videos, 6, seed=1, allow_imbalance=False)
    assert len(select_balanced(videos, 6, seed=1, allow_imbalance=True)) == 6
