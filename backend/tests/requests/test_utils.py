"""History search's query helpers (requirements §10)."""

import pytest

from app.requests.utils import fts_match, search_words


def test_match_query_quotes_and_prefixes_every_word() -> None:
    assert fts_match("bunn") == '"bunn"*'
    assert fts_match("  Big   Buck ") == '"Big"* "Buck"*'
    # FTS operators and syntax stay plain words: never OR, NOT, a column filter or a phrase.
    assert fts_match('big OR "buck" -bunny title:x NEAR(a b)') == (
        '"big"* "OR"* "buck"* "bunny"* "title"* "x"* "NEAR"* "a"* "b"*'
    )
    assert fts_match("Amélie") == '"Amélie"*'


@pytest.mark.parametrize("q", [None, "", "   ", '"*-:()', "^"])
def test_match_query_of_only_punctuation_is_none(q: str | None) -> None:
    assert fts_match(q) is None
    assert search_words(q) == []


def test_search_words_split_on_punctuation() -> None:
    assert search_words("nothing-here, s01e02") == ["nothing", "here", "s01e02"]
