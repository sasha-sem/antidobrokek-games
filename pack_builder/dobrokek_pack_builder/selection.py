from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable

from .models import TelegramVideo


class SelectionError(ValueError):
    pass


def distribution(videos: Iterable[TelegramVideo]) -> dict[str, int]:
    return dict(sorted(Counter(video.author_id for video in videos if video.author_id).items()))


def select_random(
    videos: Iterable[TelegramVideo],
    count: int,
    *,
    seed: int | str | None,
) -> list[TelegramVideo]:
    if count < 1:
        raise SelectionError("Число вопросов должно быть положительным")
    available = list(videos)
    if len(available) < count:
        raise SelectionError(f"Нужно {count} видео, но доступно {len(available)}")
    return random.Random(seed).sample(available, count)


def select_balanced(
    videos: Iterable[TelegramVideo],
    count: int,
    *,
    seed: int | str | None,
    allow_imbalance: bool,
) -> list[TelegramVideo]:
    if count < 1:
        raise SelectionError("Число вопросов должно быть положительным")
    groups: dict[str, list[TelegramVideo]] = defaultdict(list)
    for video in videos:
        if video.author_id:
            groups[video.author_id].append(video)
    if not groups:
        raise SelectionError("Нет доступных видео с распознанными авторами")
    rng = random.Random(seed)
    for values in groups.values():
        rng.shuffle(values)
    available = {author_id: len(values) for author_id, values in sorted(groups.items())}
    if sum(available.values()) < count:
        raise SelectionError(
            f"Нужно {count} видео, но доступно {sum(available.values())}. "
            f"По авторам: {available}"
        )

    author_ids = list(groups)
    rng.shuffle(author_ids)
    selected: list[TelegramVideo] = []
    if allow_imbalance:
        positions = {author_id: 0 for author_id in author_ids}
        while len(selected) < count:
            progressed = False
            for author_id in author_ids:
                index = positions[author_id]
                if index < len(groups[author_id]):
                    selected.append(groups[author_id][index])
                    positions[author_id] += 1
                    progressed = True
                    if len(selected) == count:
                        break
            if not progressed:
                break
    else:
        base, extra = divmod(count, len(author_ids))
        if any(len(groups[author_id]) < base for author_id in author_ids):
            raise SelectionError(
                f"Нельзя равномерно выбрать {count} видео. Доступно: {available}. "
                "Используйте --allow-imbalance."
            )
        extra_candidates = [author_id for author_id in author_ids if len(groups[author_id]) > base]
        if len(extra_candidates) < extra:
            raise SelectionError(
                f"Нельзя равномерно выбрать {count} видео. Доступно: {available}. "
                "Используйте --allow-imbalance."
            )
        rng.shuffle(extra_candidates)
        extra_authors = set(extra_candidates[:extra])
        for author_id in author_ids:
            take = base + (1 if author_id in extra_authors else 0)
            selected.extend(groups[author_id][:take])
    rng.shuffle(selected)
    return selected
