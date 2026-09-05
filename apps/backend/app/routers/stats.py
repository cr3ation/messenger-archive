"""Analytics: per-conversation and archive-wide."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db
from .threads import ALL_SOURCES, DEFAULT_SOURCES

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/threads/{thread_id}/stats")
def thread_stats(
    thread_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    top: int = Query(12, le=100),
):
    thread = conn.execute(
        "SELECT id, title, is_group, message_count, media_count, first_ts, last_ts "
        "FROM thread WHERE id = ?",
        (thread_id,),
    ).fetchone()
    if thread is None:
        raise HTTPException(404, "No such conversation")

    # Per-person totals come from the precomputed monthly table, so this stays
    # instant no matter how long the conversation is.
    senders = [
        dict(row)
        for row in conn.execute(
            """SELECT p.name AS sender, p.hue, p.is_owner,
                      sum(s.message_count) AS messages,
                      sum(s.word_count)    AS words,
                      sum(s.media_count)   AS media
                 FROM thread_month_stats s JOIN person p ON p.id = s.sender_id
                WHERE s.thread_id = ?
                GROUP BY s.sender_id
                ORDER BY messages DESC""",
            (thread_id,),
        )
    ]
    total_messages = sum(s["messages"] for s in senders) or 1
    for sender in senders:
        sender["share"] = round(100 * sender["messages"] / total_messages, 1)
        sender["is_owner"] = bool(sender["is_owner"])

    months = [
        dict(row)
        for row in conn.execute(
            "SELECT ym, sum(message_count) AS n FROM thread_month_stats "
            "WHERE thread_id = ? GROUP BY ym ORDER BY ym",
            (thread_id,),
        )
    ]
    years = [
        dict(row)
        for row in conn.execute(
            "SELECT substr(ym, 1, 4) AS year, sum(message_count) AS n FROM thread_month_stats "
            "WHERE thread_id = ? GROUP BY year ORDER BY year",
            (thread_id,),
        )
    ]
    hours = [
        dict(row)
        for row in conn.execute(
            "SELECT cast(strftime('%H', ts / 1000, 'unixepoch') AS INTEGER) AS hour, "
            "count(*) AS n FROM message WHERE thread_id = ? GROUP BY hour ORDER BY hour",
            (thread_id,),
        )
    ]
    weekdays = [
        dict(row)
        for row in conn.execute(
            "SELECT cast(strftime('%w', ts / 1000, 'unixepoch') AS INTEGER) AS weekday, "
            "count(*) AS n FROM message WHERE thread_id = ? GROUP BY weekday ORDER BY weekday",
            (thread_id,),
        )
    ]
    busiest = conn.execute(
        "SELECT date(ts / 1000, 'unixepoch') AS day, count(*) AS n FROM message "
        "WHERE thread_id = ? GROUP BY day ORDER BY n DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    emoji = [
        dict(row)
        for row in conn.execute(
            "SELECT emoji, n FROM thread_emoji_freq WHERE thread_id = ? ORDER BY n DESC LIMIT ?",
            (thread_id, top),
        )
    ]
    words = [
        dict(row)
        for row in conn.execute(
            "SELECT word, n FROM thread_word_freq WHERE thread_id = ? ORDER BY n DESC LIMIT ?",
            (thread_id, top),
        )
    ]
    media_kinds = [
        dict(row)
        for row in conn.execute(
            "SELECT kind, count(*) AS n FROM media WHERE thread_id = ? GROUP BY kind ORDER BY n DESC",
            (thread_id,),
        )
    ]
    active_days = conn.execute(
        "SELECT count(DISTINCT date(ts / 1000, 'unixepoch')) FROM message WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()[0]

    return {
        "thread": {
            "id": thread["id"],
            "title": thread["title"],
            "is_group": bool(thread["is_group"]),
            "message_count": thread["message_count"],
            "media_count": thread["media_count"],
            "first_ts": thread["first_ts"],
            "last_ts": thread["last_ts"],
            "active_days": active_days,
        },
        "senders": senders,
        "months": months,
        "years": years,
        "hours": hours,
        "weekdays": weekdays,
        "busiest_day": dict(busiest) if busiest else None,
        "emoji": emoji,
        "words": words,
        "media_kinds": media_kinds,
    }


@router.get("/stats")
def archive_stats(
    conn: sqlite3.Connection = Depends(get_db),
    sources: str = ",".join(DEFAULT_SOURCES),
    top: int = Query(10, le=50),
):
    wanted = [s for s in sources.split(",") if s in ALL_SOURCES] or list(DEFAULT_SOURCES)
    placeholders = ",".join("?" * len(wanted))

    totals = conn.execute(
        f"""SELECT count(*) AS threads, coalesce(sum(message_count), 0) AS messages,
                   coalesce(sum(media_count), 0) AS media,
                   min(first_ts) AS first_ts, max(last_ts) AS last_ts
              FROM thread WHERE source IN ({placeholders})""",
        wanted,
    ).fetchone()

    years = [
        dict(row)
        for row in conn.execute(
            f"""SELECT substr(s.ym, 1, 4) AS year, sum(s.message_count) AS n
                  FROM thread_month_stats s JOIN thread t ON t.id = s.thread_id
                 WHERE t.source IN ({placeholders})
                 GROUP BY year ORDER BY year""",
            wanted,
        )
    ]
    top_threads = [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, title, is_group, message_count FROM thread
                 WHERE source IN ({placeholders})
                 ORDER BY message_count DESC LIMIT ?""",
            [*wanted, top],
        )
    ]
    top_people = [
        dict(row)
        for row in conn.execute(
            f"""SELECT p.name AS sender, p.hue, sum(s.message_count) AS n
                  FROM thread_month_stats s
                  JOIN person p ON p.id = s.sender_id
                  JOIN thread t ON t.id = s.thread_id
                 WHERE t.source IN ({placeholders}) AND p.is_owner = 0
                 GROUP BY s.sender_id ORDER BY n DESC LIMIT ?""",
            [*wanted, top],
        )
    ]
    emoji = [
        dict(row)
        for row in conn.execute(
            f"""SELECT e.emoji, sum(e.n) AS n FROM thread_emoji_freq e
                  JOIN thread t ON t.id = e.thread_id
                 WHERE t.source IN ({placeholders})
                 GROUP BY e.emoji ORDER BY n DESC LIMIT ?""",
            [*wanted, top],
        )
    ]
    return {
        "totals": dict(totals),
        "years": years,
        "top_threads": [{**t, "is_group": bool(t["is_group"])} for t in top_threads],
        "top_people": top_people,
        "emoji": emoji,
    }
