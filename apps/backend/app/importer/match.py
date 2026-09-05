"""Stitch encrypted history onto the conversation it continues.

Facebook's export stops at the moment a chat was encrypted; the secure-storage
export picks up after it. To make a conversation whole again the two halves have
to be recognised as the same conversation — and the only thing the two formats
share is the set of participant names. There are no thread ids in common.

That makes matching a judgement call, so the rule is deliberately conservative:
merge only when the answer is unambiguous. A duplicate row in the sidebar is a
small annoyance; someone else's messages appearing in a friend's conversation is
not.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

SECURE_SOURCE = "secure_storage"


@dataclass
class Candidate:
    thread_id: int
    thread_key: str
    title: str
    source: str
    last_ts: int | None


@dataclass
class MatchResult:
    thread_key: str
    source: str
    merged_into: str | None = None   # title of the conversation this continues
    reason: str = "new"              # merged | ambiguous | new


class ThreadMatcher:
    """Index of existing conversations, keyed by their participant set."""

    def __init__(self, conn: sqlite3.Connection):
        # A conversation can only continue one earlier conversation. Messenger
        # allows several separate chats with the same person, and without this
        # they would all collapse into whichever one looked most recent.
        self._claimed: set[str] = set()
        self._by_participants: dict[frozenset[str], list[Candidate]] = {}
        for row in conn.execute(
            """SELECT t.id, t.thread_key, t.title, t.source, t.last_ts,
                      group_concat(p.name, char(31)) AS names
                 FROM thread t
                 JOIN thread_participant tp ON tp.thread_id = t.id
                 JOIN person p ON p.id = tp.person_id
                GROUP BY t.id"""
        ):
            key = frozenset((row["names"] or "").split("\x1f"))
            self._by_participants.setdefault(key, []).append(
                Candidate(row["id"], row["thread_key"], row["title"], row["source"], row["last_ts"])
            )

    def match(
        self,
        participants: list[str],
        title: str,
        first_ts: int | None,
        fallback_key: str,
    ) -> MatchResult:
        candidates = [
            c
            for c in self._by_participants.get(frozenset(participants), [])
            if c.thread_key not in self._claimed
        ]

        if not candidates:
            return MatchResult(thread_key=fallback_key, source=SECURE_SOURCE, reason="new")

        if len(candidates) == 1:
            return self._merge(candidates[0])

        # Several conversations share these participants — two separate chats
        # with the same person, or threads whose other party is unknown. Prefer
        # the one this history plausibly continues: the latest that still ended
        # before the new messages start.
        if first_ts is not None:
            preceding = [c for c in candidates if c.last_ts is not None and c.last_ts < first_ts]
            if preceding:
                newest = max(c.last_ts for c in preceding)  # type: ignore[type-var]
                best = [c for c in preceding if c.last_ts == newest]
                if len(best) == 1:
                    return self._merge(best[0])

        return MatchResult(thread_key=fallback_key, source=SECURE_SOURCE, reason="ambiguous")

    def _merge(self, winner: Candidate) -> MatchResult:
        self._claimed.add(winner.thread_key)
        return MatchResult(
            thread_key=winner.thread_key,
            source=winner.source,
            merged_into=winner.title,
            reason="merged",
        )

    def remember(self, participants: list[str], candidate: Candidate) -> None:
        """Register a thread created during this run, so later files can match it."""
        self._by_participants.setdefault(frozenset(participants), []).append(candidate)
