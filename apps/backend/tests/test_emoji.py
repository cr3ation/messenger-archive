"""Emoji extraction feeds both search and the statistics charts."""

from app.emoji import count_emoji, extract_emoji, normalise, normalise_query, only_emoji


def test_extracts_simple_emoji():
    assert extract_emoji("hej 👍 då 😂") == ["👍", "😂"]


def test_keeps_duplicates_for_counting():
    assert count_emoji("😂😂😂 kul")["😂"] == 3


def test_zwj_sequence_counts_as_one():
    # Family emoji: three people joined by zero-width joiners.
    assert extract_emoji("👨‍👩‍👧") == ["👨‍👩‍👧"]


def test_skin_tone_stays_attached():
    assert extract_emoji("👍🏽") == ["👍🏽"]


def test_variation_selector_is_normalised():
    # "❤" and "❤️" must collapse or search misses half the hits and the
    # top-emoji chart lists the same heart twice.
    assert normalise("❤️") == "❤"
    assert extract_emoji("❤️") == extract_emoji("❤") == ["❤"]


def test_flags_are_one_emoji():
    assert extract_emoji("🇸🇪") == ["🇸🇪"]


def test_ignores_bare_punctuation_lookalikes():
    assert extract_emoji("© 2024 Firma AB™") == []


def test_plain_text_has_no_emoji():
    assert extract_emoji("god jul och gott nytt år") == []
    assert extract_emoji(None) == []


def test_only_emoji_detects_jumbo_messages():
    assert only_emoji("😂😂")
    assert only_emoji("👍 ")
    assert not only_emoji("😂 haha")
    assert not only_emoji("")


def test_query_normalisation_dedupes_but_keeps_order():
    assert normalise_query("❤️ 👍 ❤") == ["❤", "👍"]
