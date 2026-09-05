"""Full-text and emoji search across one conversation or the whole archive."""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, Query

from ..deps import HL_END, HL_START, get_db
from ..emoji import normalise_query
from .threads import ALL_SOURCES, DEFAULT_SOURCES

router = APIRouter(prefix="/api", tags=["search"])

_PHRASE_RE = re.compile(r'"([^"]+)"')
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

SNIPPET_TOKENS = 12


def build_match(query: str) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression.

    Every term is quoted, so punctuation a user types can never be read as FTS
    syntax.  The final term gets a prefix wildcard, which is what makes
    search-as-you-type feel responsive.
    """
    phrases = _PHRASE_RE.findall(query)
    remainder = _PHRASE_RE.sub(" ", query)
    tokens = _TOKEN_RE.findall(remainder)

    parts = [f'"{p.strip()}"' for p in phrases if p.strip()]
    parts += [f'"{t}"' for t in tokens]
    if not parts:
        return None

    ends_with_phrase = query.rstrip().endswith('"')
    if tokens and not ends_with_phrase:
        parts[-1] = f"{parts[-1]}*"
    return " ".join(parts)


def _source_filter(sources: str) -> tuple[str, list[str]]:
    wanted = [s for s in sources.split(",") if s in ALL_SOURCES] or list(DEFAULT_SOURCES)
    return f"t.source IN ({','.join('?' * len(wanted))})", wanted


def _emoji_snippet(content: str | None, needles: list[str]) -> str:
    """Highlight emoji hits by hand — FTS5 never sees emoji, so snippet() can't."""
    if not content:
        return ""
    text = content
    position = min((text.find(n) for n in needles if text.find(n) >= 0), default=0)
    start = max(0, position - 40)
    end = min(len(text), position + 80)
    excerpt = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")

    # Needles are stored without U+FE0F but the text often carries it, so the
    # selector has to be swept into the highlight or it renders detached.
    for needle in needles:
        pattern = re.escape(needle) + "️?"
        excerpt = re.sub(pattern, lambda m: f"{HL_START}{m.group(0)}{HL_END}", excerpt)
    return excerpt


@router.get("/search")
def search(
    conn: sqlite3.Connection = Depends(get_db),
    q: str = "",
    thread_id: int | None = None,
    sources: str = ",".join(DEFAULT_SOURCES),
    sender: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    order: str = Query("relevance", pattern="^(relevance|newest|oldest)$"),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    query = q.strip()
    if not query:
        return {"results": [], "total": 0, "mode": "empty"}

    emoji_needles = normalise_query(query)
    text_part = query
    for needle in emoji_needles:
        text_part = text_part.replace(needle, " ")
    match = build_match(text_part)

    where = ["1=1"]
    params: list = []
    if thread_id is not None:
        where.append("m.thread_id = ?")
        params.append(thread_id)
    else:
        clause, source_params = _source_filter(sources)
        where.append(clause)
        params += source_params
    if sender:
        where.append("p.name = ?")
        params.append(sender)
    if date_from is not None:
        where.append("m.ts >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("m.ts <= ?")
        params.append(date_to)

    # Emoji live outside the FTS index (unicode61 drops them), so an emoji-only
    # query is answered from message_emoji instead.
    if emoji_needles and not match:
        mode = "emoji"
        placeholders = ",".join("?" * len(emoji_needles))
        base = f"""
            FROM message_emoji e
            JOIN message m ON m.id = e.message_id
            JOIN person p ON p.id = m.sender_id
            JOIN thread t ON t.id = m.thread_id
           WHERE e.emoji IN ({placeholders}) AND {' AND '.join(where)}
        """
        order_sql = "ORDER BY m.ts DESC" if order != "oldest" else "ORDER BY m.ts ASC"
        head_params = list(emoji_needles) + params
        total = conn.execute(
            f"SELECT count(DISTINCT m.id) {base}", head_params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT DISTINCT m.id, m.thread_id, m.seq, m.ts, m.content,
                       p.name AS sender, t.title AS thread_title, t.is_group
                {base} {order_sql} LIMIT ? OFFSET ?""",
            head_params + [limit, offset],
        ).fetchall()
        results = [
            {**dict(row), "snippet": _emoji_snippet(row["content"], emoji_needles)}
            for row in rows
        ]
    else:
        if not match:
            return {"results": [], "total": 0, "mode": "empty"}
        mode = "text"
        base = f"""
            FROM message_fts f
            JOIN message m ON m.id = f.rowid
            JOIN person p ON p.id = m.sender_id
            JOIN thread t ON t.id = m.thread_id
           WHERE message_fts MATCH ? AND {' AND '.join(where)}
        """
        order_sql = {
            "relevance": "ORDER BY bm25(message_fts)",
            "newest": "ORDER BY m.ts DESC",
            "oldest": "ORDER BY m.ts ASC",
        }[order]
        head_params = [match] + params
        total = conn.execute(f"SELECT count(*) {base}", head_params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT m.id, m.thread_id, m.seq, m.ts, m.content,
                       p.name AS sender, t.title AS thread_title, t.is_group,
                       snippet(message_fts, 0, ?, ?, '…', ?) AS snippet
                {base} {order_sql} LIMIT ? OFFSET ?""",
            [HL_START, HL_END, SNIPPET_TOKENS] + head_params + [limit, offset],
        ).fetchall()
        results = [dict(row) for row in rows]

    for result in results:
        result["is_group"] = bool(result["is_group"])

    return {"results": results, "total": total, "mode": mode, "query": query}


@router.get("/search/terms")
def search_terms(q: str = ""):
    """The terms a client should highlight in the chat view for this query."""
    emoji_needles = normalise_query(q)
    text = q
    for needle in emoji_needles:
        text = text.replace(needle, " ")
    words = [w for w in _TOKEN_RE.findall(text) if w]
    phrases = [p.strip() for p in _PHRASE_RE.findall(q) if p.strip()]
    return {"terms": phrases + words + emoji_needles}
