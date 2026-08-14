from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .authors import AuthorCatalog
from .builder import build_pack, eligible_videos
from .history import HistoryStore
from .selection import SelectionError
from .telegram import TelegramSource

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = PACKAGE_ROOT / "data" / "history.sqlite3"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Дата должна иметь формат YYYY-MM-DD") from exc


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Значение должно быть больше нуля")
    return parsed


def common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channel", default=os.getenv("TELEGRAM_CHANNEL_ID"), required=False)
    parser.add_argument("--authors", type=Path, required=True)
    parser.add_argument("--from-date", type=parse_date)
    parser.add_argument("--to-date", type=parse_date)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dobrokek-pack", description="Генератор паков викторины «Доброкек»")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Проанализировать канал без скачивания")
    common_arguments(scan)
    build = subparsers.add_parser("build", help="Скачать и собрать ZIP-пак")
    common_arguments(build)
    build.add_argument("--count", type=positive_int, default=20)
    build.add_argument("--title", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--max-duration", type=positive_int, default=60)
    build.add_argument("--max-file-size", type=positive_int, default=50, help="Лимит видео в МБ")
    build.add_argument("--allow-reuse", action="store_true")
    build.add_argument("--allow-imbalance", action="store_true")
    build.add_argument("--skip-unknown-authors", action="store_true")
    build.add_argument("--seed")
    return parser


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана переменная {name}")
    return value


async def run(args: argparse.Namespace) -> None:
    if not args.channel:
        raise RuntimeError("Укажите --channel или TELEGRAM_CHANNEL_ID")
    channel: int | str = int(args.channel) if str(args.channel).lstrip("-").isdigit() else args.channel
    catalog = AuthorCatalog.load(args.authors.resolve())
    history = HistoryStore(DEFAULT_HISTORY)
    source = TelegramSource(
        int(_required_env("TELEGRAM_API_ID")),
        _required_env("TELEGRAM_API_HASH"),
        Path(os.getenv("TELEGRAM_SESSION_PATH", "./data/dobrokek.session")).resolve(),
    )
    async with source:
        result = await source.scan(
            channel,
            catalog,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        durations = [video.duration_seconds for video in result.videos if video.duration_seconds > 0]
        counts = Counter(video.author_id for video in result.recognized)
        print(f"Сообщений в канале: {result.total_messages}")
        print(f"Видео: {len(result.videos)}")
        print(f"Распознано: {len(result.recognized)}")
        print(f"Неизвестных авторов: {len(result.unknown)}")
        print("Распределение: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
        if durations:
            print(
                "Длительность, с: "
                f"min={min(durations):.2f}, avg={statistics.fmean(durations):.2f}, max={max(durations):.2f}"
            )
        unknown = sorted({video.raw_author or "<подпись не найдена>" for video in result.unknown})
        if unknown:
            print("Неизвестные подписи:")
            for value in unknown:
                print(f"  - {value}")
        print(f"Уже использовано: {len(history.used_keys(int(channel) if isinstance(channel, int) else None))}")
        if args.command == "build":
            available = eligible_videos(
                result,
                history=history,
                max_duration_seconds=args.max_duration,
                allow_reuse=args.allow_reuse,
            )
            print(f"Доступно после фильтров: {len(available)}")
            manifest, selected_distribution = await build_pack(
                source,
                result,
                catalog,
                history,
                count=args.count,
                title=args.title,
                output=args.output,
                max_duration_seconds=args.max_duration,
                max_file_size_bytes=args.max_file_size * 1024 * 1024,
                allow_reuse=args.allow_reuse,
                allow_imbalance=args.allow_imbalance,
                skip_unknown_authors=args.skip_unknown_authors,
                seed=args.seed,
                ffmpeg_binary=os.getenv("FFMPEG_BINARY", "ffmpeg"),
                ffprobe_binary=os.getenv("FFPROBE_BINARY", "ffprobe"),
            )
            print(f"Пак {manifest['pack_id']} создан: {args.output.resolve()}")
            print("Итоговое распределение: " + ", ".join(f"{key}={value}" for key, value in selected_distribution.items()))


def main() -> None:
    load_dotenv()
    try:
        asyncio.run(run(build_parser().parse_args()))
    except (RuntimeError, ValueError, SelectionError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
