"""Everything computed *after* the raw rows are in place.

Kept separate from loading because all of it is a pure function of the message
table: it can be re-run at any time, and must be re-run after every import.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

from ..stopwords import STOPWORDS

TOP_WORDS_PER_THREAD = 300
TOP_EMOJI_PER_THREAD = 100

# Unicode letters only: no digits, no underscores, at least two characters.
WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def assign_seq(conn: sqlite3.Connection) -> None:
    """Give every message its 0-based position within its thread.

    This is what makes "jump to July 2014" and "jump to search hit" O(1) in a
    virtualised list: the frontend can scroll straight to an absolute index
    without having loaded anything before it.
    """
    conn.execute(
        """
        UPDATE message
           SET seq = ordered.s
          FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY thread_id ORDER BY ts, id) - 1 AS s
                  FROM message
               ) AS ordered
         WHERE message.id = ordered.id
        """
    )


def refresh_thread_totals(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE thread
           SET first_ts      = totals.first_ts,
               last_ts       = totals.last_ts,
               message_count = totals.n
          FROM (
                SELECT thread_id, min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS n
                  FROM message GROUP BY thread_id
               ) AS totals
         WHERE thread.id = totals.thread_id
        """
    )
    conn.execute(
        """
        UPDATE thread
           SET media_count = coalesce((
                 SELECT count(*) FROM media
                  WHERE media.thread_id = thread.id AND media.kind <> 'sticker'
                    AND media.is_missing = 0
               ), 0)
        """
    )
    # Threads that exist but hold no messages would otherwise keep stale totals.
    conn.execute(
        "UPDATE thread SET message_count = 0, first_ts = NULL, last_ts = NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM message WHERE message.thread_id = thread.id)"
    )


def detect_owner(conn: sqlite3.Connection, forced_name: str | None = None) -> str | None:
    """Mark the archive's owner: the person present in the most conversations.

    Ties are broken by message count.  ``--owner`` overrides the heuristic.
    """
    if forced_name:
        row = conn.execute("SELECT id, name FROM person WHERE name = ?", (forced_name,)).fetchone()
        if row is None:
            raise ValueError(f"No person named {forced_name!r} in the archive")
    else:
        row = conn.execute(
            """
            SELECT p.id, p.name
              FROM person p
              JOIN thread_participant tp ON tp.person_id = p.id
         LEFT JOIN message m ON m.sender_id = p.id
             GROUP BY p.id
             ORDER BY count(DISTINCT tp.thread_id) DESC, count(m.id) DESC
             LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

    conn.execute("UPDATE person SET is_owner = 0 WHERE is_owner = 1")
    conn.execute("UPDATE person SET is_owner = 1 WHERE id = ?", (row["id"],))
    return row["name"]


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO message_fts(message_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO message_fts(message_fts) VALUES('optimize')")


def rebuild_month_stats(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM thread_month_stats")
    conn.execute(
        """
        INSERT INTO thread_month_stats (thread_id, ym, sender_id, message_count, word_count, media_count)
        SELECT thread_id,
               strftime('%Y-%m', ts / 1000, 'unixepoch') AS ym,
               sender_id,
               count(*),
               -- cheap word count: spaces + 1, good enough for a trend line
               coalesce(sum(CASE WHEN content IS NULL OR content = '' THEN 0
                                 ELSE length(content) - length(replace(content, ' ', '')) + 1 END), 0),
               coalesce(sum(has_media), 0)
          FROM message
         GROUP BY thread_id, ym, sender_id
        """
    )


def rebuild_word_freq(conn: sqlite3.Connection) -> None:
    """Top words per thread, streamed thread by thread so memory stays flat."""
    conn.execute("DELETE FROM thread_word_freq")

    current_thread: int | None = None
    counter: Counter[str] = Counter()

    def flush() -> None:
        if current_thread is None or not counter:
            return
        conn.executemany(
            "INSERT INTO thread_word_freq (thread_id, word, n) VALUES (?, ?, ?) "
            "ON CONFLICT(thread_id, word) DO UPDATE SET n = excluded.n",
            [
                (current_thread, word, n)
                for word, n in counter.most_common(TOP_WORDS_PER_THREAD)
            ],
        )

    cursor = conn.execute(
        "SELECT thread_id, content FROM message "
        "WHERE content IS NOT NULL AND content <> '' ORDER BY thread_id"
    )
    for thread_id, content in cursor:
        if thread_id != current_thread:
            flush()
            current_thread = thread_id
            counter = Counter()
        for word in WORD_RE.findall(content.lower()):
            if word not in STOPWORDS:
                counter[word] += 1
    flush()


def rebuild_emoji_freq(conn: sqlite3.Connection) -> None:
    """Per-thread emoji totals from message text *and* reactions."""
    conn.execute("DELETE FROM thread_emoji_freq")
    conn.execute(
        """
        INSERT INTO thread_emoji_freq (thread_id, emoji, n)
        -- char(65039) is U+FE0F; stripping it collapses "❤" and "❤️" into one entry,
        -- matching how app.emoji.normalise() stores them in message_emoji.
        SELECT thread_id, emoji, sum(n) FROM (
            SELECT thread_id, emoji, n FROM message_emoji
            UNION ALL
            SELECT m.thread_id, replace(r.emoji, char(65039), ''), 1
              FROM reaction r JOIN message m ON m.id = r.message_id
        )
        GROUP BY thread_id, emoji
        """
    )
    # Keep only the head of each thread's distribution.
    conn.execute(
        """
        DELETE FROM thread_emoji_freq
         WHERE rowid NOT IN (
               SELECT rowid FROM (
                 SELECT rowid,
                        ROW_NUMBER() OVER (PARTITION BY thread_id ORDER BY n DESC) AS rank
                   FROM thread_emoji_freq
               ) WHERE rank <= ?
         )
        """,
        (TOP_EMOJI_PER_THREAD,),
    )


def recheck_media(conn: sqlite3.Connection) -> tuple[int, int]:
    """Re-stat every media file and refresh `is_missing`.

    Needed because a photo's bytes often arrive in a different zip from the JSON
    that references it.  Whatever order the parts were unpacked in, this final
    pass gives an honest answer about what is actually on disk.
    """
    updates = []
    missing = 0
    for row in conn.execute(
        """SELECT md.id, md.uri, md.kind, md.size_bytes, md.is_missing, s.export_root
             FROM media md JOIN import_source s ON s.id = md.source_id"""
    ).fetchall():
        # Attachments Meta failed to export hold a sentinel, not a path. Without
        # this guard they would be stat()ed and could be marked as present.
        if row["kind"] == "unavailable":
            missing += 1
            if not row["is_missing"]:
                updates.append((None, 1, row["id"]))
            continue

        path = Path(row["export_root"]) / row["uri"]
        try:
            size = path.stat().st_size
            is_missing = 0
        except OSError:
            size = None
            is_missing = 1
        missing += is_missing
        if is_missing != row["is_missing"] or size != row["size_bytes"]:
            updates.append((size, is_missing, row["id"]))

    if updates:
        conn.executemany(
            "UPDATE media SET size_bytes = ?, is_missing = ? WHERE id = ?", updates
        )
    total = conn.execute("SELECT count(*) FROM media").fetchone()[0]
    return total, missing


def run_all(conn: sqlite3.Connection, owner: str | None = None) -> str | None:
    assign_seq(conn)
    recheck_media(conn)
    refresh_thread_totals(conn)
    detected = detect_owner(conn, owner)
    rebuild_fts(conn)
    rebuild_month_stats(conn)
    rebuild_word_freq(conn)
    rebuild_emoji_freq(conn)
    conn.execute("ANALYZE")
    conn.commit()
    return detected
