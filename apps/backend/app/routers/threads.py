"""Conversation list, message windows, timeline navigation and media gallery."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import MESSAGE_COLUMNS, get_db, serialise_messages

router = APIRouter(prefix="/api", tags=["threads"])

# secure_storage holds everything sent after a chat was encrypted, so it must
# be visible by default — it is the only place recent messages exist.
DEFAULT_SOURCES = ("inbox", "e2ee_cutover", "secure_storage", "archived_threads")
ALL_SOURCES = DEFAULT_SOURCES + ("message_requests", "filtered_threads")

GALLERY_KINDS = ("photo", "video", "gif", "file", "audio")


def _participants_for(conn: sqlite3.Connection, thread_ids: list[int]) -> dict[int, list[dict]]:
    if not thread_ids:
        return {}
    placeholders = ",".join("?" * len(thread_ids))
    out: dict[int, list[dict]] = {tid: [] for tid in thread_ids}
    for row in conn.execute(
        f"""SELECT tp.thread_id, p.name, p.hue, p.is_owner
              FROM thread_participant tp JOIN person p ON p.id = tp.person_id
             WHERE tp.thread_id IN ({placeholders})
             ORDER BY p.is_owner, p.name""",
        thread_ids,
    ):
        out[row["thread_id"]].append(
            {"name": row["name"], "hue": row["hue"], "is_owner": bool(row["is_owner"])}
        )
    return out


@router.get("/threads")
def list_threads(
    conn: sqlite3.Connection = Depends(get_db),
    q: str = "",
    sources: str = ",".join(DEFAULT_SOURCES),
    limit: int = Query(500, le=2000),
    offset: int = 0,
):
    wanted = [s for s in sources.split(",") if s in ALL_SOURCES] or list(DEFAULT_SOURCES)
    # Named parameters throughout: the ranking expression sits in the SELECT
    # clause, so positional binding order would not match the argument order.
    params: dict = {f"src{i}": source for i, source in enumerate(wanted)}
    where = [f"t.source IN ({','.join(f':src{i}' for i in range(len(wanted)))})"]
    rank = "0"

    if q.strip():
        params["needle"] = f"%{q.strip().lower()}%"
        # `p.is_owner = 0` matters: you are a participant in every single thread,
        # so without it searching your own name returns the entire archive.
        where.append(
            """(ulower(t.title) LIKE :needle
                OR EXISTS (SELECT 1 FROM thread_participant tp
                             JOIN person p ON p.id = tp.person_id
                            WHERE tp.thread_id = t.id
                              AND p.is_owner = 0
                              AND ulower(p.name) LIKE :needle))"""
        )
        # Searching a person's name should surface that person, not every group
        # they were ever in. Recency only breaks ties within a rank.
        rank = """
            CASE
              WHEN t.is_group = 0                 THEN 0
              WHEN ulower(t.title) LIKE :needle    THEN 1
              ELSE                                     2
            END
        """

    params["limit"] = limit
    params["offset"] = offset

    rows = conn.execute(
        f"""
        SELECT t.id, t.thread_key, t.title, t.source, t.is_group, t.participant_count,
               t.image_uri, t.first_ts, t.last_ts, t.message_count, t.media_count,
               last.content AS last_content, last.has_media AS last_has_media,
               last.sender AS last_sender,
               {rank} AS match_rank
          FROM thread t
     LEFT JOIN (
               SELECT m.thread_id, m.content, m.has_media, p.name AS sender,
                      ROW_NUMBER() OVER (PARTITION BY m.thread_id ORDER BY m.ts DESC, m.id DESC) AS rn
                 FROM message m JOIN person p ON p.id = m.sender_id
               ) last ON last.thread_id = t.id AND last.rn = 1
         WHERE {' AND '.join(where)}
         ORDER BY match_rank, t.last_ts DESC NULLS LAST
         LIMIT :limit OFFSET :offset
        """,
        params,
    ).fetchall()

    threads = [dict(row) for row in rows]
    participants = _participants_for(conn, [t["id"] for t in threads])
    for thread in threads:
        thread["is_group"] = bool(thread["is_group"])
        thread["participants"] = participants.get(thread["id"], [])
        thread["others"] = [p["name"] for p in thread["participants"] if not p["is_owner"]]
    return {"threads": threads}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM thread WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such conversation")
    thread = dict(row)
    thread["is_group"] = bool(thread["is_group"])
    thread["participants"] = _participants_for(conn, [thread_id])[thread_id]
    thread["others"] = [p["name"] for p in thread["participants"] if not p["is_owner"]]
    return thread


@router.get("/threads/{thread_id}/messages")
def get_messages(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    from_seq: int = 0,
    limit: int = Query(200, le=500),
):
    """A window of the conversation, addressed by absolute position.

    The frontend's virtualiser knows the thread's total length up front, so it
    asks for exactly the slice it is about to paint — no cursors, no offsets
    that shift underneath it.
    """
    rows = conn.execute(
        f"""SELECT {MESSAGE_COLUMNS}
              FROM message m JOIN person p ON p.id = m.sender_id
             WHERE m.thread_id = ? AND m.seq >= ?
             ORDER BY m.seq LIMIT ?""",
        (thread_id, max(from_seq, 0), limit),
    ).fetchall()
    return {"messages": serialise_messages(conn, rows), "from_seq": max(from_seq, 0)}


@router.get("/threads/{thread_id}/locate")
def locate(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    message_id: int | None = None,
    ts: int | None = None,
    ym: str | None = None,
):
    """Translate a message id, timestamp or 'YYYY-MM' into a scroll position."""
    if message_id is not None:
        row = conn.execute(
            "SELECT seq, ts FROM message WHERE id = ? AND thread_id = ?", (message_id, thread_id)
        ).fetchone()
    elif ym is not None:
        row = conn.execute(
            """SELECT seq, ts FROM message
                WHERE thread_id = ? AND strftime('%Y-%m', ts / 1000, 'unixepoch') >= ?
                ORDER BY seq LIMIT 1""",
            (thread_id, ym),
        ).fetchone()
    elif ts is not None:
        row = conn.execute(
            "SELECT seq, ts FROM message WHERE thread_id = ? AND ts >= ? ORDER BY seq LIMIT 1",
            (thread_id, ts),
        ).fetchone()
    else:
        raise HTTPException(400, "Pass one of message_id, ts or ym")

    if row is None:
        # Past the end of the conversation: land on the last message.
        row = conn.execute(
            "SELECT seq, ts FROM message WHERE thread_id = ? ORDER BY seq DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Conversation has no messages")
    return {"seq": row["seq"], "ts": row["ts"]}


@router.get("/threads/{thread_id}/timeline")
def timeline(thread_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Months that contain messages, each with the seq to jump to."""
    rows = conn.execute(
        """SELECT strftime('%Y-%m', ts / 1000, 'unixepoch') AS ym,
                  count(*) AS n, min(seq) AS seq
             FROM message WHERE thread_id = ?
            GROUP BY ym ORDER BY ym""",
        (thread_id,),
    ).fetchall()
    return {"months": [dict(row) for row in rows]}


def _gallery_kinds(kinds: str) -> list[str]:
    return [k for k in kinds.split(",") if k in GALLERY_KINDS] or ["photo"]


# The gallery is virtualised, so positions have to be computed against exactly
# the order the grid paints in. Kept in one place so ordering can never drift
# between the listing, the position lookup and the month index.
GALLERY_ORDER = "md.ts DESC, md.id DESC"


@router.get("/threads/{thread_id}/media")
def thread_media(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    kinds: str = "photo,video,gif",
    limit: int = Query(120, le=500),
    offset: int = 0,
):
    wanted = _gallery_kinds(kinds)
    placeholders = ",".join("?" * len(wanted))
    rows = conn.execute(
        f"""SELECT md.id, md.message_id, md.kind, md.filename, md.ts, md.size_bytes,
                   m.seq, p.name AS sender
              FROM media md
              JOIN message m ON m.id = md.message_id
              JOIN person p ON p.id = m.sender_id
             WHERE md.thread_id = ? AND md.kind IN ({placeholders}) AND md.is_missing = 0
             ORDER BY {GALLERY_ORDER}
             LIMIT ? OFFSET ?""",
        [thread_id, *wanted, limit, offset],
    ).fetchall()

    counts = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, count(*) AS n FROM media WHERE thread_id = ? AND is_missing = 0 "
            "GROUP BY kind",
            (thread_id,),
        )
    }
    total = conn.execute(
        f"SELECT count(*) FROM media WHERE thread_id = ? AND kind IN ({placeholders}) "
        "AND is_missing = 0",
        [thread_id, *wanted],
    ).fetchone()[0]

    return {
        "items": [dict(row) for row in rows],
        "counts": counts,
        "total": total,
        "offset": offset,
    }


@router.get("/threads/{thread_id}/media/locate")
def locate_media(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    kinds: str = "photo,video,gif",
    media_id: int | None = None,
    ts: int | None = None,
):
    """Position of a media item in the gallery, so the grid can scroll straight to it.

    ``media_id`` answers "where is the photo I clicked in the chat"; ``ts``
    answers "what was shared around where I am reading", which is how the
    gallery stays in step with the conversation.
    """
    wanted = _gallery_kinds(kinds)
    placeholders = ",".join("?" * len(wanted))
    base = f"""
        SELECT md.id, md.kind, md.ts,
               ROW_NUMBER() OVER (ORDER BY {GALLERY_ORDER}) - 1 AS offset
          FROM media md
         WHERE md.thread_id = ? AND md.kind IN ({placeholders}) AND md.is_missing = 0
    """
    params = [thread_id, *wanted]

    if media_id is not None:
        row = conn.execute(
            f"SELECT * FROM ({base}) WHERE id = ?", [*params, media_id]
        ).fetchone()
    elif ts is not None:
        # Newest-first ordering means "at or before this moment" is the first row
        # whose timestamp has dropped to or below it.
        row = conn.execute(
            f"SELECT * FROM ({base}) WHERE ts <= ? ORDER BY offset LIMIT 1", [*params, ts]
        ).fetchone()
        if row is None:
            # Reading before anything was shared: land on the oldest item.
            row = conn.execute(
                f"SELECT * FROM ({base}) ORDER BY offset DESC LIMIT 1", params
            ).fetchone()
    else:
        raise HTTPException(400, "Pass either media_id or ts")

    if row is None:
        raise HTTPException(404, "No media matches")
    return {"offset": row["offset"], "media_id": row["id"], "kind": row["kind"], "ts": row["ts"]}


@router.get("/threads/{thread_id}/media/timeline")
def media_timeline(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    kinds: str = "photo,video,gif",
):
    """Months that contain media, each with the gallery offset to jump to."""
    wanted = _gallery_kinds(kinds)
    placeholders = ",".join("?" * len(wanted))
    rows = conn.execute(
        f"""
        SELECT ym, count(*) AS n, min(offset) AS offset FROM (
            SELECT strftime('%Y-%m', md.ts / 1000, 'unixepoch') AS ym,
                   ROW_NUMBER() OVER (ORDER BY {GALLERY_ORDER}) - 1 AS offset
              FROM media md
             WHERE md.thread_id = ? AND md.kind IN ({placeholders}) AND md.is_missing = 0
        )
        GROUP BY ym ORDER BY ym
        """,
        [thread_id, *wanted],
    ).fetchall()
    return {"months": [dict(row) for row in rows]}
