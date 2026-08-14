from pathlib import Path

import pytest

from dobrokek_pack_builder.authors import AuthorCatalog, extract_author_name


def test_extracts_last_code_entity_after_person_marker() -> None:
    text = "Подпись\n\n👤Саша"
    prefix = "Подпись\n\n👤"
    entity = {
        "type": "code",
        "offset": len(prefix.encode("utf-16-le")) // 2,
        "length": 4,
    }
    assert extract_author_name(text, [entity]) == "Саша"


def test_extracts_utf16_entity_after_emoji() -> None:
    text = "🤡\n👤Миша"
    prefix = "🤡\n👤"
    entity = {
        "type": "code",
        "offset": len(prefix.encode("utf-16-le")) // 2,
        "length": len("Миша"),
    }
    assert extract_author_name(text, [entity]) == "Миша"


def test_fallback_strips_markdown() -> None:
    assert extract_author_name("Текст\n👤  `  Илья  `") == "Илья"


def test_aliases_and_unknown(tmp_path: Path) -> None:
    path = tmp_path / "authors.yaml"
    path.write_text(
        "authors:\n"
        "  - id: sasha\n    display_name: Саша\n    aliases: [Александр]\n"
        "  - id: misha\n    display_name: Миша\n    aliases: [Михаил]\n",
        encoding="utf-8",
    )
    catalog = AuthorCatalog.load(path)
    assert catalog.resolve("  александр ").id == "sasha"
    assert catalog.resolve("Незнакомец") is None


def test_duplicate_alias_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "authors.yaml"
    path.write_text(
        "authors:\n"
        "  - id: first\n    display_name: First\n    aliases: [Same]\n"
        "  - id: second\n    display_name: Second\n    aliases: [same]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="двух авторов"):
        AuthorCatalog.load(path)
