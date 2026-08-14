from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import QuizError
from app.models.tables import Answer, Author, Meme, QuestionRun, Reaction

SORT_COLUMNS = {
    "rating": "rating",
    "votes_total": "votes_total",
    "likes": "likes",
    "guess_accuracy_percent": "guess_accuracy_percent",
    "last_shown_at": "last_shown_at",
}

CSV_FIELDS = [
    "telegram_chat_id",
    "telegram_message_id",
    "author_id",
    "author_name",
    "likes",
    "dislikes",
    "votes_total",
    "rating",
    "approval_percent",
    "games_shown",
    "players_guessed",
    "correct_guesses",
    "guess_accuracy_percent",
    "first_seen_at",
    "last_shown_at",
]


class StatsService:
    def __init__(self, session_factory: async_sessionmaker):
        self.sessions = session_factory

    async def rows(
        self,
        *,
        min_votes: int = 0,
        author_id: str | None = None,
        sort: str = "rating",
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        if sort not in SORT_COLUMNS:
            raise QuizError(f"Неизвестная сортировка: {sort}")
        if order not in ("asc", "desc"):
            raise QuizError("order должен быть asc или desc")

        reaction_stats = (
            select(
                Reaction.meme_id.label("meme_id"),
                func.sum(case((Reaction.value == 1, 1), else_=0)).label("likes"),
                func.sum(case((Reaction.value == -1, 1), else_=0)).label("dislikes"),
                func.count(Reaction.id).label("votes_total"),
                func.sum(Reaction.value).label("rating"),
            )
            .group_by(Reaction.meme_id)
            .subquery()
        )
        game_stats = (
            select(
                QuestionRun.meme_id.label("meme_id"),
                func.count(func.distinct(QuestionRun.room_id)).label("games_shown"),
                func.max(QuestionRun.started_at).label("last_shown_at"),
                func.count(Answer.id).label("players_guessed"),
                func.sum(case((Answer.is_correct.is_(True), 1), else_=0)).label("correct_guesses"),
            )
            .outerjoin(Answer, Answer.question_run_id == QuestionRun.id)
            .group_by(QuestionRun.meme_id)
            .subquery()
        )
        query = (
            select(
                Meme,
                Author.display_name.label("author_name"),
                func.coalesce(reaction_stats.c.likes, 0).label("likes"),
                func.coalesce(reaction_stats.c.dislikes, 0).label("dislikes"),
                func.coalesce(reaction_stats.c.votes_total, 0).label("votes_total"),
                func.coalesce(reaction_stats.c.rating, 0).label("rating"),
                func.coalesce(game_stats.c.games_shown, 0).label("games_shown"),
                func.coalesce(game_stats.c.players_guessed, 0).label("players_guessed"),
                func.coalesce(game_stats.c.correct_guesses, 0).label("correct_guesses"),
                game_stats.c.last_shown_at,
            )
            .join(Author, Author.id == Meme.author_id)
            .outerjoin(reaction_stats, reaction_stats.c.meme_id == Meme.id)
            .outerjoin(game_stats, game_stats.c.meme_id == Meme.id)
            .where(func.coalesce(reaction_stats.c.votes_total, 0) >= min_votes)
        )
        if author_id:
            query = query.where(Meme.author_id == author_id)
        async with self.sessions() as session:
            raw = (await session.execute(query)).all()
        result: list[dict[str, Any]] = []
        for row in raw:
            votes = int(row.votes_total)
            guessed = int(row.players_guessed)
            result.append(
                {
                    "telegram_chat_id": row.Meme.telegram_chat_id,
                    "telegram_message_id": row.Meme.telegram_message_id,
                    "author_id": row.Meme.author_id,
                    "author_name": row.author_name,
                    "likes": int(row.likes),
                    "dislikes": int(row.dislikes),
                    "votes_total": votes,
                    "rating": int(row.rating),
                    "approval_percent": round(int(row.likes) / votes * 100, 2) if votes else None,
                    "games_shown": int(row.games_shown),
                    "players_guessed": guessed,
                    "correct_guesses": int(row.correct_guesses),
                    "guess_accuracy_percent": round(int(row.correct_guesses) / guessed * 100, 2) if guessed else None,
                    "first_seen_at": row.Meme.created_at.isoformat() + "Z",
                    "last_shown_at": row.last_shown_at.isoformat() + "Z" if row.last_shown_at else None,
                }
            )
        reverse = order == "desc"

        def key(item: dict[str, Any]) -> tuple[Any, int]:
            value = item[sort]
            return (value is not None, value if value is not None else 0)

        result.sort(key=key, reverse=reverse)
        if sort == "rating":
            result.sort(key=lambda item: (item["rating"], item["votes_total"]), reverse=reverse)
        return result

    @staticmethod
    def csv(rows: list[dict[str, Any]]) -> str:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in CSV_FIELDS} for row in rows)
        return stream.getvalue()
