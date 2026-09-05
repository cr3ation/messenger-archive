"""Repair Facebook's mojibake.

Facebook writes its message exports by taking the original UTF-8 bytes and
escaping each *byte* as a separate ``\\uXXXX`` codepoint.  So the name
``Engström`` (UTF-8: ``45 6e 67 73 74 72 c3 b6 6d``) is written as
``Engstr\\u00c3\\u00b6m`` and a JSON parser hands us the string ``Engströ¶m``.

Recovering the original is a matter of encoding the string back to Latin-1
(which maps U+0080..U+00FF straight onto the byte values) and decoding it as
UTF-8 again.

The critical property is that the repair must be a *no-op* on text that is
already correct: the Swedish word ``Allmän`` becomes ``b'Allm\\xe4n'`` in
Latin-1, which is not valid UTF-8, so the decode fails and we keep the string
untouched.  We only ever accept a repair that decodes cleanly end to end.
"""

from __future__ import annotations

# Codepoints that can appear in mojibake: the Latin-1 supplement block is where
# raw UTF-8 bytes land when they are mistaken for individual characters.
_SUSPECT_RANGE = range(0x80, 0x100)

# A repair pass is only attempted when the string contains a plausible UTF-8
# lead byte from that block.  0xC2-0xF4 covers everything from "Â" (nbsp and
# punctuation) up to 4-byte emoji sequences.
_LEAD_BYTES = frozenset(chr(c) for c in range(0xC2, 0xF5))

_MAX_PASSES = 3


def looks_mojibaked(text: str) -> bool:
    """True when *text* contains a byte pattern typical of double-encoded UTF-8."""
    if text.isascii():
        return False
    for i, ch in enumerate(text):
        if ch in _LEAD_BYTES and i + 1 < len(text) and ord(text[i + 1]) in _SUSPECT_RANGE:
            return True
    return False


def repair_text(text: str) -> str:
    """Undo Facebook's byte-as-codepoint mangling, leaving correct text alone.

    Applied repeatedly because a handful of exports are doubly mangled; each
    pass must decode cleanly or the string is returned as it was.
    """
    if not text or text.isascii():
        return text

    for _ in range(_MAX_PASSES):
        if not looks_mojibaked(text):
            break
        try:
            candidate = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == text:
            break
        text = candidate

    return text


def repair(value):
    """Recursively repair every string inside a parsed JSON structure."""
    if isinstance(value, str):
        return repair_text(value)
    if isinstance(value, dict):
        return {repair_text(k): repair(v) for k, v in value.items()}
    if isinstance(value, list):
        return [repair(v) for v in value]
    return value
