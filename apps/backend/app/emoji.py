"""Emoji extraction.

FTS5's ``unicode61`` tokenizer classifies emoji as separators, so they never
reach the full-text index.  Emoji are therefore pulled out here and stored in
their own table, which serves both emoji search and the "most used emoji"
statistic.

The pattern below matches whole grapheme sequences rather than individual
codepoints, so ``👨‍👩‍👧`` (three people joined by ZWJ) and ``🎙️`` (a base plus
variation selector) each count as one emoji instead of several.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_BASE = (
    "[\U0001F000-\U0001FAFF"       # pictographs, emoticons, symbols, extended
    "\U00002600-\U000026FF"        # misc symbols
    "\U00002700-\U000027BF"        # dingbats
    "\U00002B00-\U00002BFF"        # arrows / geometric
    "\U00002190-\U000021FF"        # arrows
    "\U00002300-\U000023FF"        # technical (⌚ ⏰ ⏳ …)
    "\U0001F1E6-\U0001F1FF"        # regional indicators (handled again below)
    "\U00002194-\U00002199"
    "\U000024C2\U00003030\U0000303D\U00003297\U00003299"
    "\U000000A9\U000000AE\U00002122]"
)
_MOD = "[\U0001F3FB-\U0001F3FF️︎\U0001F9B0-\U0001F9B3]"
_KEYCAP = "[0-9#*]️?⃣"
_FLAG = "[\U0001F1E6-\U0001F1FF]{2}"

EMOJI_RE = re.compile(
    f"(?:{_FLAG})|(?:{_KEYCAP})|(?:{_BASE}{_MOD}*(?:‍{_BASE}{_MOD}*)*)"
)

# Lone ©, ® and ™ are far more often punctuation than emoji in chat text.
_IGNORED = {"©", "®", "™"}

# U+FE0F only asks for a colourful rendering; "❤" and "❤️" are the same emoji and
# must collapse, or search misses half the hits and the top-emoji chart lists
# the same heart twice.  Applied to both stored emoji and search queries.
_VARIATION_SELECTOR = "️"


def normalise(emoji: str) -> str:
    return emoji.replace(_VARIATION_SELECTOR, "") or emoji


def extract_emoji(text: str | None) -> list[str]:
    """Return every emoji in *text*, in order, keeping duplicates."""
    if not text:
        return []
    return [normalise(m) for m in EMOJI_RE.findall(text) if m not in _IGNORED]


def count_emoji(text: str | None) -> Counter[str]:
    return Counter(extract_emoji(text))


def contains_emoji(text: str) -> bool:
    return bool(extract_emoji(text))


def only_emoji(text: str) -> bool:
    """True when *text* is nothing but emoji and whitespace (used for jumbo rendering)."""
    stripped = EMOJI_RE.sub("", text or "")
    return bool(text) and not stripped.strip()


def normalise_query(text: str) -> list[str]:
    """Emoji from a search query, deduplicated but order-preserving."""
    seen: dict[str, None] = {}
    for e in extract_emoji(text):
        seen.setdefault(e, None)
    return list(seen)


def total(counters: Iterable[Counter[str]]) -> Counter[str]:
    out: Counter[str] = Counter()
    for c in counters:
        out.update(c)
    return out
