"""Write parsed threads into SQLite.

Everything here is an UPSERT keyed on a stable identity (``thread.thread_key``,
``message.dedupe_key``) so importing the same export twice — or importing a
second export that overlaps the first — converges instead of duplicating.
"""

from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

from ..emoji import count_emoji
from .parse import MediaRef, ParsedThread
from .parse_secure import UNAVAILABLE_KIND
from .reader import UnpackedArchive

BATCH = 2000


class PersonCache:
    """Name → person id, created on demand."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ids: dict[str, int] = {
            row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM person")
        }

    def id_for(self, name: str) -> int:
        cached = self._ids.get(name)
        if cached is not None:
            return cached
        hue = zlib.crc32(name.encode("utf-8")) % 360
        self.conn.execute(
            "INSERT INTO person (name, hue) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
            (name, hue),
        )
        person_id = self.conn.execute(
            "SELECT id FROM person WHERE name = ?", (name,)
        ).fetchone()["id"]
        self._ids[name] = person_id
        return person_id


def upsert_import_source(conn: sqlite3.Connection, archive_name: str, export_root: Path, now: int) -> int:
    conn.execute(
        """
        INSERT INTO import_source (archive_name, export_root, imported_at)
        VALUES (?, ?, ?)
        ON CONFLICT(archive_name) DO UPDATE SET
            export_root = excluded.export_root,
            imported_at = excluded.imported_at
        """,
        (archive_name, str(export_root), now),
    )
    return conn.execute(
        "SELECT id FROM import_source WHERE archive_name = ?", (archive_name,)
    ).fetchone()["id"]


def record_archives(
    conn: sqlite3.Connection,
    source_id: int,
    archives: list[UnpackedArchive],
    now: int,
) -> None:
    """Note which individual zips fed this export root, for the UI's archive list."""
    conn.executemany(
        """
        INSERT INTO import_archive (name, source_id, unpacked_at, file_count, size_bytes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            source_id   = excluded.source_id,
            unpacked_at = excluded.unpacked_at,
            file_count  = excluded.file_count,
            size_bytes  = coalesce(excluded.size_bytes, import_archive.size_bytes)
        """,
        [(a.name, source_id, now, a.file_count, a.size_bytes) for a in archives],
    )


def upsert_thread(conn: sqlite3.Connection, people: PersonCache, thread: ParsedThread) -> int:
    conn.execute(
        """
        INSERT INTO thread (thread_key, title, source, is_group, participant_count,
                            image_uri, is_still_participant)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(thread_key) DO UPDATE SET
            title                = excluded.title,
            source               = excluded.source,
            is_group             = excluded.is_group,
            participant_count    = max(thread.participant_count, excluded.participant_count),
            image_uri            = coalesce(excluded.image_uri, thread.image_uri),
            is_still_participant = excluded.is_still_participant
        """,
        (
            thread.thread_key,
            thread.title,
            thread.source,
            int(thread.is_group),
            len(thread.participants),
            thread.image_uri,
            None if thread.is_still_participant is None else int(thread.is_still_participant),
        ),
    )
    thread_id = conn.execute(
        "SELECT id FROM thread WHERE thread_key = ?", (thread.thread_key,)
    ).fetchone()["id"]

    conn.executemany(
        "INSERT INTO thread_participant (thread_id, person_id) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        [(thread_id, people.id_for(name)) for name in thread.participants],
    )
    return thread_id


def _message_ids(conn: sqlite3.Connection, keys: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for start in range(0, len(keys), 900):  # stay under SQLite's parameter limit
        chunk = keys[start : start + 900]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT id, dedupe_key FROM message WHERE dedupe_key IN ({placeholders})", chunk
        ):
            out[row["dedupe_key"]] = row["id"]
    return out


def load_messages(
    conn: sqlite3.Connection,
    people: PersonCache,
    thread: ParsedThread,
    thread_id: int,
    source_id: int,
    export_root: Path,
) -> int:
    """Insert/refresh a thread's messages, media, reactions and emoji index."""
    written = 0

    for start in range(0, len(thread.messages), BATCH):
        batch = thread.messages[start : start + BATCH]

        conn.executemany(
            """
            INSERT INTO message (thread_id, sender_id, ts, content, share_link, share_text,
                                 sticker_uri, call_duration, is_unsent, has_media, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                thread_id     = excluded.thread_id,
                sender_id     = excluded.sender_id,
                ts            = excluded.ts,
                content       = excluded.content,
                share_link    = excluded.share_link,
                share_text    = excluded.share_text,
                sticker_uri   = excluded.sticker_uri,
                call_duration = excluded.call_duration,
                is_unsent     = excluded.is_unsent,
                has_media     = excluded.has_media
            """,
            [
                (
                    thread_id,
                    people.id_for(m.sender),
                    m.ts,
                    m.content,
                    m.share_link,
                    m.share_text,
                    m.sticker_uri,
                    m.call_duration,
                    int(m.is_unsent),
                    int(bool(m.media)),
                    m.dedupe_key,
                )
                for m in batch
            ],
        )

        ids = _message_ids(conn, [m.dedupe_key for m in batch])

        media_rows = []
        reaction_rows = []
        emoji_rows = []

        for message in batch:
            message_id = ids.get(message.dedupe_key)
            if message_id is None:
                continue
            written += 1

            refs = list(message.media)
            if message.sticker_uri:
                # Stored as media too, so the sticker image is servable by id.
                # The gallery filters `kind='sticker'` out by default.
                refs.append(
                    MediaRef(
                        kind="sticker",
                        uri=message.sticker_uri,
                        filename=Path(message.sticker_uri).name,
                        creation_ts=None,
                    )
                )

            for ref in refs:
                if ref.kind == UNAVAILABLE_KIND:
                    # Meta's exporter failed to fetch this one; its URI is a
                    # sentinel, so never treat it as a path on disk.
                    size, missing = None, 1
                else:
                    absolute = export_root / ref.uri
                    try:
                        size = absolute.stat().st_size
                        missing = 0
                    except OSError:
                        size = None
                        missing = 1
                media_rows.append(
                    (
                        message_id,
                        thread_id,
                        source_id,
                        ref.kind,
                        ref.uri,
                        ref.filename,
                        message.ts,
                        ref.creation_ts,
                        size,
                        missing,
                    )
                )

            for emoji_char, actor in message.reactions:
                reaction_rows.append((message_id, people.id_for(actor), emoji_char))

            for emoji_char, n in count_emoji(message.content).items():
                emoji_rows.append((message_id, thread_id, emoji_char, n))

        if media_rows:
            conn.executemany(
                """
                INSERT INTO media (message_id, thread_id, source_id, kind, uri, filename,
                                   ts, creation_ts, size_bytes, is_missing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id, uri) DO UPDATE SET
                    kind        = excluded.kind,
                    ts          = excluded.ts,
                    creation_ts = excluded.creation_ts,
                    size_bytes  = excluded.size_bytes,
                    is_missing  = excluded.is_missing,
                    source_id   = excluded.source_id
                """,
                media_rows,
            )
        if reaction_rows:
            conn.executemany(
                "INSERT INTO reaction (message_id, actor_id, emoji) VALUES (?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                reaction_rows,
            )
        if emoji_rows:
            conn.executemany(
                "INSERT INTO message_emoji (message_id, thread_id, emoji, n) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(message_id, emoji) DO UPDATE SET n = excluded.n",
                emoji_rows,
            )

    return written

