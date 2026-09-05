"""User input must never reach FTS5 as syntax."""

import pytest

from app.routers.search import build_match


def test_single_word_gets_prefix_wildcard():
    # Search-as-you-type: "jula" should already match "julafton".
    assert build_match("jula") == '"jula"*'


def test_multiple_words_are_anded():
    assert build_match("god jul") == '"god" "jul"*'


def test_quoted_phrase_is_kept_intact():
    assert build_match('"god jul"') == '"god jul"'


def test_phrase_plus_word():
    assert build_match('"god jul" allihopa') == '"god jul" "allihopa"*'


@pytest.mark.parametrize(
    "dangerous",
    ['NEAR(a b)', 'a OR b', 'a AND b', 'col:value', 'a*b', '"', '((', 'a NOT b', '^start'],
)
def test_fts_operators_are_neutralised(dangerous):
    """Whatever the user types, every term ends up quoted — never operators."""
    match = build_match(dangerous)
    if match is None:
        return
    for token in match.split():
        assert token.startswith('"'), f"unquoted token {token!r} in {match!r}"


def test_punctuation_only_query_matches_nothing():
    assert build_match("!!! ???") is None
    assert build_match("") is None


def test_swedish_characters_survive():
    assert build_match("förälder") == '"förälder"*'
