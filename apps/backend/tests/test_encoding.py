"""The repair must fix Facebook's mangling without touching correct text."""

import pytest

from app.encoding import looks_mojibaked, repair, repair_text

# Left side is exactly what json.load() hands back for Facebook's
# "Ã¶"-style escapes; right side is what the name really is.
MANGLED = [
    ("Henrik EngstrÃ¶m", "Henrik Engström"),
    ("Matilda MattsvÃ¥g", "Matilda Mattsvåg"),
    ("Daniel KylÃ©n", "Daniel Kylén"),
    ("AllmÃ¤n chat", "Allmän chat"),
    ("Facebook-anvÃ¤ndare", "Facebook-användare"),
    # Emoji: four raw UTF-8 bytes, one per codepoint, plus a variation selector.
    ("ðï¸", "🎙️"),
    ("ð", "🙏"),
    ("ð", "👍"),
]

# Text that is already correct, including the characters most at risk of being
# "repaired" into nonsense.
ALREADY_FINE = [
    "Allmän chat",
    "Henrik Engström",
    "Kan något i bandet svara på denna fråga?",
    "Ångström",
    "café",
    "naïve",
    "🎙️ inspelning",
    "plain ascii",
    "",
    "Ärlighet varar längst",
]


@pytest.mark.parametrize("mangled,expected", MANGLED)
def test_repairs_facebook_mojibake(mangled, expected):
    assert repair_text(mangled) == expected


@pytest.mark.parametrize("text", ALREADY_FINE)
def test_leaves_correct_text_alone(text):
    assert repair_text(text) == text


@pytest.mark.parametrize("text", ALREADY_FINE)
def test_repair_is_idempotent(text):
    once = repair_text(text)
    assert repair_text(once) == once


@pytest.mark.parametrize("mangled,expected", MANGLED)
def test_repairing_twice_changes_nothing(mangled, expected):
    assert repair_text(repair_text(mangled)) == expected


def test_detects_mojibake_only_when_present():
    assert looks_mojibaked("EngstrÃ¶m")
    assert not looks_mojibaked("Engström")
    assert not looks_mojibaked("ascii only")


def test_repairs_nested_structures():
    payload = {
        "participants": [{"name": "Henrik EngstrÃ¶m"}],
        "title": "AllmÃ¤n chat",
        "messages": [{"content": "hi","reactions": ["ð"]}],
    }
    fixed = repair(payload)
    assert fixed["participants"][0]["name"] == "Henrik Engström"
    assert fixed["title"] == "Allmän chat"
    assert fixed["messages"][0]["reactions"] == ["👍"]
