from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .models import Author

PERSON_RE = re.compile(r"👤\s*(.+)$", re.MULTILINE)
MARKDOWN_RE = re.compile(r"[`*_~\[\]]")


def clean_author_name(value: str) -> str:
    value = value.replace("👤", "")
    value = MARKDOWN_RE.sub("", value)
    return " ".join(value.split()).strip()


def _utf16_slice(text: str, offset: int, length: int) -> str:
    encoded = text.encode("utf-16-le")
    return encoded[offset * 2 : (offset + length) * 2].decode("utf-16-le")


def _entity_value(entity: Any, name: str, default: Any = None) -> Any:
    if isinstance(entity, dict):
        return entity.get(name, default)
    return getattr(entity, name, default)


def _is_code_entity(entity: Any) -> bool:
    entity_type = _entity_value(entity, "type", "")
    return entity_type == "code" or entity.__class__.__name__ == "MessageEntityCode"


def extract_author_name(
    text: str | None,
    entities: Iterable[Any] | None = None,
    entity_texts: Iterable[tuple[Any, str]] | None = None,
) -> str | None:
    """Extract the last author marker, preferring Telegram code entities."""
    body = text or ""
    candidates: list[tuple[int, str]] = []
    if entity_texts is not None:
        for entity, entity_text in entity_texts:
            if not _is_code_entity(entity):
                continue
            offset = int(_entity_value(entity, "offset", 0))
            prefix = _utf16_slice(body, 0, offset)
            if "👤" in entity_text or prefix.rstrip().endswith("👤"):
                candidates.append((offset, entity_text))
    else:
        for entity in entities or ():
            if not _is_code_entity(entity):
                continue
            offset = int(_entity_value(entity, "offset", 0))
            length = int(_entity_value(entity, "length", 0))
            entity_text = str(_entity_value(entity, "text", "")) or _utf16_slice(
                body, offset, length
            )
            prefix = _utf16_slice(body, 0, offset)
            if "👤" in entity_text or prefix.rstrip().endswith("👤"):
                candidates.append((offset, entity_text))
    if candidates:
        cleaned = clean_author_name(max(candidates, key=lambda item: item[0])[1])
        return cleaned or None
    matches = list(PERSON_RE.finditer(body))
    if not matches:
        return None
    cleaned = clean_author_name(matches[-1].group(1))
    return cleaned or None


class AuthorCatalog:
    def __init__(self, authors: Iterable[Author]):
        self.authors = tuple(authors)
        if len(self.authors) < 2:
            raise ValueError("В authors.yaml должно быть не менее двух авторов")
        ids: set[str] = set()
        aliases: dict[str, Author] = {}
        for author in self.authors:
            if author.id in ids:
                raise ValueError(f"Повторяющийся id автора: {author.id}")
            ids.add(author.id)
            for alias in (*author.aliases, author.display_name):
                key = clean_author_name(alias).casefold()
                if key in aliases and aliases[key].id != author.id:
                    raise ValueError(f"Алиас {alias!r} задан для двух авторов")
                aliases[key] = author
        self._aliases = aliases

    @classmethod
    def load(cls, path: Path) -> AuthorCatalog:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_authors = payload.get("authors")
        if not isinstance(raw_authors, list):
            raise ValueError("В authors.yaml ожидается список authors")
        authors = []
        for item in raw_authors:
            if not isinstance(item, dict):
                raise ValueError("Каждый автор должен быть объектом")
            authors.append(
                Author(
                    id=str(item["id"]),
                    display_name=clean_author_name(str(item["display_name"])),
                    aliases=tuple(str(alias) for alias in item.get("aliases", [])),
                )
            )
        return cls(authors)

    def resolve(self, raw_name: str | None) -> Author | None:
        if not raw_name:
            return None
        return self._aliases.get(clean_author_name(raw_name).casefold())
