"""End-to-end import against a synthetic export, including the multi-zip case."""

import json
import os
import zipfile
from pathlib import Path

import pytest

OWNER = "Henrik Engström"
FRIEND = "Fanny Ekblom Johansson"


def mangle(text: str) -> str:
    """Re-create Facebook's byte-as-codepoint escaping, so the fixture is realistic."""
    return text.encode("utf-8").decode("latin-1")


def thread_json(thread_key: str, title: str, photo_uri: str) -> dict:
    base = f"your_facebook_activity/messages/inbox/{thread_key}"
    return {
        "participants": [{"name": mangle(OWNER)}, {"name": mangle(FRIEND)}],
        "title": mangle(title),
        "is_still_participant": True,
        "thread_path": f"inbox/{thread_key}",
        "messages": [
            {
                "sender_name": mangle(FRIEND),
                "timestamp_ms": 1_500_000_000_000,
                # Kept in Swedish deliberately: test_emoji_and_fts_indexes_are_searchable
                # searches this text for "jul", which exercises the tokenizer on
                # non-ASCII letters. Translating it would quietly weaken that test.
                "content": mangle("God jul och gott nytt år! 🎄"),
                "reactions": [{"reaction": mangle("👍"), "actor": mangle(OWNER)}],
                "is_geoblocked_for_viewer": False,
            },
            {
                "sender_name": mangle(OWNER),
                "timestamp_ms": 1_500_000_060_000,
                "content": mangle("Tack detsamma ❤️"),
                "is_geoblocked_for_viewer": False,
            },
            {
                "sender_name": mangle(OWNER),
                "timestamp_ms": 1_500_000_120_000,
                "photos": [{"uri": f"{base}/photos/{photo_uri}", "creation_timestamp": 1_500_000_000}],
                "is_geoblocked_for_viewer": False,
            },
        ],
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ARCHIVE_DB", str(data / "archive.db"))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("CONVERSATIONS_DIR", raising=False)
    return tmp_path


def make_zips(tmp_path: Path) -> tuple[Path, Path]:
    """Split a conversation the way Facebook does: JSON in one zip, photo in another."""
    thread_key = "fannyekblomjohansson_123"
    base = f"your_facebook_activity/messages/inbox/{thread_key}"

    text_zip = tmp_path / "export-part-AAAA.zip"
    with zipfile.ZipFile(text_zip, "w") as zf:
        zf.writestr(
            f"{base}/message_1.json",
            json.dumps(thread_json(thread_key, "Fanny Ekblom Johansson", "photo.jpg")),
        )

    media_zip = tmp_path / "export-part-BBBB.zip"
    with zipfile.ZipFile(media_zip, "w") as zf:
        zf.writestr(f"{base}/photos/photo.jpg", b"\xff\xd8\xff\xe0 fake jpeg bytes")

    return text_zip, media_zip


def test_imports_split_archives_into_one_root(workspace):
    from app import db
    from app.importer import import_sources

    text_zip, media_zip = make_zips(workspace)
    import_sources([text_zip, media_zip], reset=True)

    conn = db.connect()
    threads = conn.execute("SELECT * FROM thread").fetchall()
    assert len(threads) == 1
    # Encoding survived the round trip.
    assert threads[0]["title"] == "Fanny Ekblom Johansson"
    assert conn.execute("SELECT count(*) FROM message").fetchone()[0] == 3

    # The photo lives in a different archive from its JSON — the whole reason
    # every part unpacks into a shared root.
    media = conn.execute("SELECT uri, is_missing FROM media").fetchall()
    assert len(media) == 1
    assert media[0]["is_missing"] == 0

    assert conn.execute("SELECT name FROM person WHERE is_owner = 1").fetchone()[0] == OWNER
    conn.close()


def test_zips_are_deleted_only_when_asked(workspace):
    from app.importer import import_sources

    text_zip, media_zip = make_zips(workspace)
    import_sources([text_zip, media_zip], reset=True, delete_zips=False)
    assert text_zip.exists() and media_zip.exists()

    import_sources([text_zip, media_zip], reset=True, delete_zips=True)
    assert not text_zip.exists() and not media_zip.exists()


def test_reimport_is_idempotent_and_keeps_message_ids(workspace):
    """Bookmarks point at message ids, so a second import must not renumber them."""
    from app import db
    from app.importer import import_sources

    text_zip, media_zip = make_zips(workspace)
    import_sources([text_zip, media_zip], reset=True)

    conn = db.connect()
    before = conn.execute("SELECT id, dedupe_key, seq FROM message ORDER BY seq").fetchall()
    conn.execute(
        "INSERT INTO bookmark (message_id, created_at) VALUES (?, ?)", (before[0]["id"], 0)
    )
    conn.commit()
    conn.close()

    import_sources([text_zip, media_zip])

    conn = db.connect()
    after = conn.execute("SELECT id, dedupe_key, seq FROM message ORDER BY seq").fetchall()
    assert [tuple(row) for row in before] == [tuple(row) for row in after]
    assert conn.execute("SELECT count(*) FROM bookmark").fetchone()[0] == 1
    conn.close()


def test_seq_is_dense_and_ordered(workspace):
    from app import db
    from app.importer import import_sources

    text_zip, media_zip = make_zips(workspace)
    import_sources([text_zip, media_zip], reset=True)

    conn = db.connect()
    rows = conn.execute("SELECT seq, ts FROM message ORDER BY seq").fetchall()
    assert [row["seq"] for row in rows] == list(range(len(rows)))
    assert [row["ts"] for row in rows] == sorted(row["ts"] for row in rows)
    conn.close()


def test_emoji_and_fts_indexes_are_searchable(workspace):
    from app import db
    from app.importer import import_sources

    text_zip, media_zip = make_zips(workspace)
    import_sources([text_zip, media_zip], reset=True)

    conn = db.connect()
    hits = conn.execute(
        "SELECT count(*) FROM message_fts WHERE message_fts MATCH ?", ('"jul"*',)
    ).fetchone()[0]
    assert hits >= 1

    # Stored without the variation selector, so both spellings find it.
    assert conn.execute(
        "SELECT count(*) FROM message_emoji WHERE emoji = ?", ("❤",)
    ).fetchone()[0] == 1
    # Reactions feed the emoji chart too.
    assert conn.execute(
        "SELECT n FROM thread_emoji_freq WHERE emoji = ?", ("👍",)
    ).fetchone()[0] == 1
    conn.close()


def test_refuses_zip_slip(workspace, tmp_path):
    """A member pointing outside the target must never be written."""
    from app.importer import reader

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        # Disguised as a real export so it gets past format detection and the
        # extraction guard is what actually stops it.
        zf.writestr("your_facebook_activity/messages/inbox/x/message_1.json", "{}")
        zf.writestr("../../escaped.txt", "nope")

    with pytest.raises(ValueError, match="outside target"):
        reader._safe_extract(evil, tmp_path / "target", lambda _line: None)

    assert not (tmp_path.parent / "escaped.txt").exists()


def test_unrecognised_zip_is_refused_before_extraction(workspace, tmp_path):
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("holiday.jpg", b"not an export")

    from app.importer import reader

    with pytest.raises(reader.ExportNotFound):
        reader.resolve_sources([junk], tmp_path / "conversations")


def test_archive_set_name_uses_common_prefix():
    from app.importer.reader import archive_set_name

    parts = [
        Path("/host/facebook-cr3ation-2026-08-05-Ki9KTCZR.zip"),
        Path("/host/facebook-cr3ation-2026-08-05-D547AjoQ.zip"),
    ]
    assert archive_set_name(parts) == "facebook-cr3ation-2026-08-05"
    assert archive_set_name([]) == "facebook"


def test_missing_media_is_flagged(workspace):
    """A photo whose bytes never arrived must be reported, not silently shown."""
    from app import db
    from app.importer import import_sources

    text_zip, _media_zip = make_zips(workspace)
    import_sources([text_zip], reset=True)  # JSON only: the photo zip is absent

    conn = db.connect()
    assert conn.execute("SELECT count(*) FROM media WHERE is_missing = 1").fetchone()[0] == 1
    conn.close()


def test_environment_is_isolated(workspace):
    assert os.environ["DATA_DIR"].startswith(str(workspace))
