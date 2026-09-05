"""Starred messages.

Bookmarks reference `message.id`, which is stable across re-imports because the
row is matched on its content-derived `dedupe_key` — so adding next year's
export does not scatter the stars.
"""

from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..deps import get_db

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


class BookmarkIn(BaseModel):
    message_id: int
    note: str | None = None


@router.get("")
def list_bookmarks(
    conn: sqlite3.Connection = Depends(get_db),
    thread_id: int | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    where = ["1=1"]
    params: list = []
    if thread_id is not None:
        where.append("m.thread_id = ?")
        params.append(thread_id)

    rows = conn.execute(
        f"""SELECT b.message_id, b.created_at, b.note,
                   m.thread_id, m.seq, m.ts, m.content, m.has_media,
                   p.name AS sender, t.title AS thread_title, t.is_group
              FROM bookmark b
              JOIN message m ON m.id = b.message_id
              JOIN person p ON p.id = m.sender_id
              JOIN thread t ON t.id = m.thread_id
             WHERE {' AND '.join(where)}
             ORDER BY b.created_at DESC
             LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    total = conn.execute("SELECT count(*) FROM bookmark").fetchone()[0]
    return {
        "bookmarks": [{**dict(row), "is_group": bool(row["is_group"])} for row in rows],
        "total": total,
    }


@router.post("")
def add_bookmark(payload: BookmarkIn, conn: sqlite3.Connection = Depends(get_db)):
    exists = conn.execute("SELECT 1 FROM message WHERE id = ?", (payload.message_id,)).fetchone()
    if not exists:
        raise HTTPException(404, "No such message")
    conn.execute(
        "INSERT INTO bookmark (message_id, created_at, note) VALUES (?, ?, ?) "
        "ON CONFLICT(message_id) DO UPDATE SET note = excluded.note",
        (payload.message_id, int(time.time()), payload.note),
    )
    conn.commit()
    return {"message_id": payload.message_id, "bookmarked": True}


@router.delete("/{message_id}")
def remove_bookmark(message_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM bookmark WHERE message_id = ?", (message_id,))
    conn.commit()
    return {"message_id": message_id, "bookmarked": False}
