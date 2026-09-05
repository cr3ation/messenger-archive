"""Messenger's encrypted-chat export, and stitching it onto existing history."""

import json
import zipfile
from pathlib import Path

import pytest

OWNER = "Henrik Engström"

# Names that are *already* correct UTF-8 in this format. They must survive the
# mojibake repair untouched — a repair that fires here would corrupt them.
SWEDISH_NAMES = ["Linnea Östberg", "Matilda Mattsvåg", "Oda Martin Åhrman", "Emma Rosén"]


def dyi_mangle(text: str) -> str:
    """Facebook's byte-as-codepoint escaping, used only by the DYI fixtures."""
    return text.encode("utf-8").decode("latin-1")


def secure_thread(
    name: str,
    other: str,
    messages: list[dict],
    participants: list[str] | None = None,
) -> tuple[str, str]:
    return (
        f"{name}.json",
        json.dumps(
            {
                "participants": participants or [OWNER, other],
                "threadName": name,
                "messages": messages,
            },
            ensure_ascii=False,
        ),
    )


def msg(sender: str, ts: int, text: str = "", kind: str = "text", **extra) -> dict:
    return {
        "senderName": sender,
        "timestamp": ts,
        "text": text,
        "type": kind,
        "isUnsent": extra.pop("isUnsent", False),
        "media": extra.pop("media", []),
        "reactions": extra.pop("reactions", []),
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ARCHIVE_DB", str(data / "archive.db"))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("EXPORTS_DIR", raising=False)
    monkeypatch.delenv("CONVERSATIONS_DIR", raising=False)
    return tmp_path


def build_secure_zip(root: Path, name: str = "messages.zip") -> Path:
    path = root / name
    entries = [
        secure_thread(
            "Erika Karlestedt_38",
            "Erika Karlestedt",
            [
                msg("Erika Karlestedt", 1_700_000_000_000, "hej igen efter krypteringen"),
                msg(OWNER, 1_700_000_060_000, "https://example.com/x", kind="link"),
                msg(
                    "Erika Karlestedt",
                    1_700_000_120_000,
                    "",
                    kind="media",
                    media=[{"uri": "./media/aaa.jpeg"}, {"uri": "Failed to download media"}],
                    reactions=[{"actor": OWNER, "reaction": "❤"}],
                ),
                msg("Erika Karlestedt", 1_700_000_180_000, "User unsent a message",
                    kind="placeholder", isUnsent=True),
            ],
        ),
        secure_thread(
            "Linnea Östberg_7",
            "Linnea Östberg",
            [msg("Linnea Östberg", 1_700_000_000_000, "ny kontakt")],
        ),
    ]

    with zipfile.ZipFile(path, "w") as zf:
        for filename, payload in entries:
            zf.writestr(filename, payload)
        zf.writestr("media/aaa.jpeg", b"\xff\xd8\xff\xe0 fake jpeg")
    return path


def build_dyi_zip(root: Path, name: str = "facebook-2026-01-01-AAAA.zip") -> Path:
    """A Facebook export that ends *before* the encrypted one starts."""
    path = root / name
    key = "erikakarlestedt_999"
    base = f"your_facebook_activity/messages/e2ee_cutover/{key}"
    payload = {
        "participants": [{"name": dyi_mangle(OWNER)}, {"name": dyi_mangle("Erika Karlestedt")}],
        "title": dyi_mangle("Erika Karlestedt"),
        "is_still_participant": True,
        "thread_path": f"e2ee_cutover/{key}",
        "messages": [
            {"sender_name": dyi_mangle("Erika Karlestedt"), "timestamp_ms": 1_600_000_000_000,
             "content": dyi_mangle("innan krypteringen")},
            {"sender_name": dyi_mangle(OWNER), "timestamp_ms": 1_600_000_060_000,
             "content": dyi_mangle("sista före brytet")},
        ],
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{base}/message_1.json", json.dumps(payload))
    return path


# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #

def test_detects_both_formats(workspace):
    from app.importer.reader import FORMAT_DYI, FORMAT_SECURE, classify_zip

    assert classify_zip(build_secure_zip(workspace)) == FORMAT_SECURE
    assert classify_zip(build_dyi_zip(workspace)) == FORMAT_DYI


def test_formats_unpack_into_separate_roots(workspace):
    """Mixing them in one root would leave the DYI locator hunting among loose JSON."""
    from app import db
    from app.importer.reader import FORMAT_DYI, FORMAT_SECURE, resolve_sources

    roots = resolve_sources(
        [build_dyi_zip(workspace), build_secure_zip(workspace)], db.conversations_dir()
    )
    by_format = {root.format: root for root in roots}
    assert set(by_format) == {FORMAT_DYI, FORMAT_SECURE}
    assert by_format[FORMAT_DYI].root != by_format[FORMAT_SECURE].root


def test_unknown_zip_is_rejected(workspace):
    from app.importer.reader import ExportNotFound, classify_zip

    junk = workspace / "junk.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("notes.txt", "nothing to see")
    with pytest.raises(ExportNotFound):
        classify_zip(junk)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def test_message_types_are_mapped(workspace):
    from app import db
    from app.importer import import_sources

    import_sources([build_secure_zip(workspace)], reset=True)
    conn = db.connect()

    link = conn.execute(
        "SELECT content, share_link FROM message WHERE share_link IS NOT NULL"
    ).fetchone()
    assert link["share_link"] == "https://example.com/x" == link["content"]

    # Meta's "User unsent a message" filler is not stored as if it were content.
    unsent = conn.execute("SELECT content, is_unsent FROM message WHERE is_unsent = 1").fetchone()
    assert unsent["content"] is None

    assert conn.execute(
        "SELECT count(*) FROM reaction WHERE emoji = ?", ("❤",)
    ).fetchone()[0] == 1
    conn.close()


def test_failed_media_is_recorded_not_invented(workspace):
    from app import db
    from app.importer import import_sources

    import_sources([build_secure_zip(workspace)], reset=True)
    conn = db.connect()

    rows = {r["kind"]: r for r in conn.execute("SELECT kind, uri, is_missing FROM media")}
    assert rows["photo"]["is_missing"] == 0

    failed = rows["unavailable"]
    assert failed["is_missing"] == 1
    # The sentinel must never be mistaken for a path on disk.
    assert "media/" not in failed["uri"]

    # It must not inflate the count of media you can actually open.
    assert conn.execute("SELECT media_count FROM thread WHERE title = ?", ("Erika Karlestedt",)
                        ).fetchone()[0] == 1
    conn.close()


def test_thread_title_drops_the_file_index(workspace):
    from app.importer.parse_secure import thread_title

    assert thread_title("Adam Wistedt_28") == "Adam Wistedt"
    assert thread_title("Nationaldagsfirande_61") == "Nationaldagsfirande"
    assert thread_title("Erika Karlestedt") == "Erika Karlestedt"


@pytest.mark.parametrize("name", SWEDISH_NAMES)
def test_correct_swedish_names_survive_untouched(name):
    """This format is already valid UTF-8; repairing it would corrupt it."""
    from app.encoding import repair_text

    assert repair_text(name) == name


def test_two_failed_attachments_on_one_message_both_survive(workspace):
    from app import db
    from app.importer import import_sources

    path = workspace / "messages.zip"
    with zipfile.ZipFile(path, "w") as zf:
        filename, payload = secure_thread(
            "Adam Wistedt_1",
            "Adam Wistedt",
            [msg("Adam Wistedt", 1_700_000_000_000, "", kind="media",
                 media=[{"uri": "Failed to download media"},
                        {"uri": "Failed to download media"}])],
        )
        zf.writestr(filename, payload)

    import_sources([path], reset=True)
    conn = db.connect()
    # A shared sentinel URI would have collapsed these into one row.
    assert conn.execute("SELECT count(*) FROM media WHERE kind = 'unavailable'").fetchone()[0] == 2
    conn.close()


# --------------------------------------------------------------------------- #
# Stitching onto existing history
# --------------------------------------------------------------------------- #

def test_encrypted_history_continues_the_existing_conversation(workspace):
    """The whole point: one continuous timeline across the encryption cut-over."""
    from app import db
    from app.importer import import_sources

    import_sources([build_dyi_zip(workspace)], reset=True)
    import_sources([build_secure_zip(workspace)])

    conn = db.connect()
    threads = conn.execute(
        "SELECT id, title, message_count, source FROM thread WHERE title = 'Erika Karlestedt'"
    ).fetchall()
    assert len(threads) == 1, "the two halves should be one conversation"

    thread = threads[0]
    assert thread["message_count"] == 6      # 2 from the DYI export + 4 encrypted
    assert thread["source"] == "e2ee_cutover"  # keeps the original conversation's identity

    rows = conn.execute(
        "SELECT seq, ts FROM message WHERE thread_id = ? ORDER BY seq", (thread["id"],)
    ).fetchall()
    assert [r["seq"] for r in rows] == list(range(6))
    assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)
    conn.close()


def test_unmatched_conversation_becomes_a_new_thread(workspace):
    from app import db
    from app.importer import import_sources

    import_sources([build_dyi_zip(workspace)], reset=True)
    import_sources([build_secure_zip(workspace)])

    conn = db.connect()
    row = conn.execute(
        "SELECT source, message_count FROM thread WHERE title = 'Linnea Östberg'"
    ).fetchone()
    assert row["source"] == "secure_storage"
    assert row["message_count"] == 1
    conn.close()


def test_ambiguous_match_is_kept_separate(workspace):
    """Two candidate conversations with no clear predecessor: never guess."""
    from app import db
    from app.importer import import_sources
    from app.importer.match import ThreadMatcher

    # Two existing conversations with the same participants, both ending *after*
    # the encrypted history starts, so neither can be its predecessor.
    import_sources([build_dyi_zip(workspace)], reset=True)
    conn = db.connect()
    for key, title in (("dup_a", "Erika Karlestedt"), ("dup_b", "Erika Karlestedt")):
        conn.execute(
            "INSERT INTO thread (thread_key, title, source, is_group, participant_count, last_ts) "
            "VALUES (?, ?, 'inbox', 0, 2, ?)",
            (key, title, 1_900_000_000_000),
        )
        thread_id = conn.execute("SELECT id FROM thread WHERE thread_key = ?", (key,)).fetchone()[0]
        for name in (OWNER, "Erika Karlestedt"):
            person = conn.execute("SELECT id FROM person WHERE name = ?", (name,)).fetchone()[0]
            conn.execute(
                "INSERT INTO thread_participant (thread_id, person_id) VALUES (?, ?)",
                (thread_id, person),
            )
    conn.execute("DELETE FROM thread WHERE thread_key = 'erikakarlestedt_999'")
    conn.commit()

    matcher = ThreadMatcher(conn)
    result = matcher.match(
        [OWNER, "Erika Karlestedt"], "Erika Karlestedt", 1_700_000_000_000, "secure:x"
    )
    assert result.reason == "ambiguous"
    assert result.thread_key == "secure:x"
    assert result.source == "secure_storage"
    conn.close()


def test_ambiguity_resolved_by_the_conversation_it_follows(workspace):
    from app import db
    from app.importer import import_sources
    from app.importer.match import ThreadMatcher

    import_sources([build_dyi_zip(workspace)], reset=True)
    conn = db.connect()
    # A second candidate that ends *after* the encrypted history starts, so the
    # original DYI thread is the only plausible predecessor.
    conn.execute(
        "INSERT INTO thread (thread_key, title, source, is_group, participant_count, last_ts) "
        "VALUES ('later', 'Erika Karlestedt', 'inbox', 0, 2, ?)", (1_900_000_000_000,)
    )
    thread_id = conn.execute("SELECT id FROM thread WHERE thread_key = 'later'").fetchone()[0]
    for name in (OWNER, "Erika Karlestedt"):
        person = conn.execute("SELECT id FROM person WHERE name = ?", (name,)).fetchone()[0]
        conn.execute(
            "INSERT INTO thread_participant (thread_id, person_id) VALUES (?, ?)",
            (thread_id, person),
        )
    conn.commit()

    result = ThreadMatcher(conn).match(
        [OWNER, "Erika Karlestedt"], "Erika Karlestedt", 1_700_000_000_000, "secure:x"
    )
    assert result.reason == "merged"
    assert result.thread_key == "erikakarlestedt_999"
    conn.close()


def test_reimport_is_idempotent_and_keeps_bookmarks(workspace):
    from app import db
    from app.importer import import_sources

    import_sources([build_dyi_zip(workspace)], reset=True)
    import_sources([build_secure_zip(workspace)])

    conn = db.connect()
    before = conn.execute("SELECT id, dedupe_key, seq FROM message ORDER BY id").fetchall()
    conn.execute("INSERT INTO bookmark (message_id, created_at) VALUES (?, 0)", (before[0]["id"],))
    conn.commit()
    conn.close()

    import_sources([build_secure_zip(workspace)])

    conn = db.connect()
    after = conn.execute("SELECT id, dedupe_key, seq FROM message ORDER BY id").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
    assert conn.execute("SELECT count(*) FROM bookmark").fetchone()[0] == 1
    conn.close()


# --------------------------------------------------------------------------- #
# Reset safety, now that archives live inside DATA_DIR
# --------------------------------------------------------------------------- #

def test_purge_never_touches_the_database_or_thumbnails(workspace):
    from app import db
    from app.importer import import_sources
    from app.importer.runner import purge_conversations

    import_sources([build_secure_zip(workspace)], reset=True)

    thumbs = db.data_dir() / "thumbs"
    thumbs.mkdir(exist_ok=True)
    (thumbs / "1.webp").write_bytes(b"cached")

    assert list(db.conversations_dir().iterdir())
    purge_conversations(lambda _line: None)

    assert list(db.conversations_dir().iterdir()) == []
    assert db.db_path().exists(), "the database must survive a purge"
    assert (thumbs / "1.webp").exists(), "the thumbnail cache must survive a purge"


def test_purge_refuses_to_delete_data_dir_itself(workspace, monkeypatch):
    from app import db
    from app.importer.runner import purge_conversations

    monkeypatch.setenv("CONVERSATIONS_DIR", str(db.data_dir()))
    with pytest.raises(RuntimeError, match="DATA_DIR"):
        purge_conversations(lambda _line: None)
