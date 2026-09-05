"""Shared request helpers: database handle and message serialisation."""

from __future__ import annotations

import sqlite3
from typing import Iterable, Iterator

from . import db

# Sentinels wrapping search hits.  Deliberately not HTML: the frontend splits on
# them and renders the pieces as text nodes, so message content can never inject
# markup no matter what it contains.
HL_START = ""
HL_END = ""


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def owner_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM person WHERE is_owner = 1 LIMIT 1").fetchone()
    return row["id"] if row else None


def _chunks(values: list, size: int = 900) -> Iterator[list]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def attach_details(conn: sqlite3.Connection, messages: list[dict]) -> list[dict]:
    """Fill in media, reactions and bookmark flags for a page of messages.

    Done as three set-based queries rather than per message — the chat window
    asks for 200 rows at a time and N+1 here would be felt on every scroll.
    """
    if not messages:
        return messages

    by_id = {m["id"]: m for m in messages}
    for message in messages:
        message["media"] = []
        message["reactions"] = []
        message["bookmarked"] = False

    ids = list(by_id)
    for chunk in _chunks(ids):
        placeholders = ",".join("?" * len(chunk))

        for row in conn.execute(
            f"""SELECT id, message_id, kind, filename, size_bytes, is_missing
                  FROM media WHERE message_id IN ({placeholders}) ORDER BY id""",
            chunk,
        ):
            by_id[row["message_id"]]["media"].append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "filename": row["filename"],
                    "size_bytes": row["size_bytes"],
                    "is_missing": bool(row["is_missing"]),
                }
            )

        for row in conn.execute(
            f"""SELECT r.message_id, r.emoji, p.name AS actor
                  FROM reaction r JOIN person p ON p.id = r.actor_id
                 WHERE r.message_id IN ({placeholders})""",
            chunk,
        ):
            by_id[row["message_id"]]["reactions"].append(
                {"emoji": row["emoji"], "actor": row["actor"]}
            )

        for row in conn.execute(
            f"SELECT message_id FROM bookmark WHERE message_id IN ({placeholders})", chunk
        ):
            by_id[row["message_id"]]["bookmarked"] = True

    return messages


MESSAGE_COLUMNS = """
    m.id, m.thread_id, m.seq, m.ts, m.content, m.share_link, m.share_text,
    m.sticker_uri, m.call_duration, m.is_unsent, m.has_media,
    p.name AS sender, p.hue AS sender_hue, p.is_owner AS is_owner
"""


def row_to_message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "seq": row["seq"],
        "ts": row["ts"],
        "content": row["content"],
        "share_link": row["share_link"],
        "share_text": row["share_text"],
        "sticker_uri": row["sticker_uri"],
        "call_duration": row["call_duration"],
        "is_unsent": bool(row["is_unsent"]),
        "sender": row["sender"],
        "sender_hue": row["sender_hue"],
        "is_own": bool(row["is_owner"]),
    }


def serialise_messages(conn: sqlite3.Connection, rows: Iterable[sqlite3.Row]) -> list[dict]:
    return attach_details(conn, [row_to_message(row) for row in rows])
