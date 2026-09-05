"""Drives the import: resolve → parse → load → derive."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .. import db
from . import derive, load, reader
from .match import Candidate, ThreadMatcher
from .parse import parse_thread
from .parse_secure import iter_secure_threads, parse_secure_thread, read_participants


@dataclass
class ImportProgress:
    state: str = "idle"          # idle | unpacking | running | deriving | done | error
    archive: str = ""
    threads_total: int = 0
    threads_done: int = 0
    messages: int = 0
    media: int = 0
    owner: str | None = None
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    # How encrypted conversations were reconciled with existing history.
    merged: int = 0
    created: int = 0
    ambiguous: int = 0
    log: list[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-200]
        print(line, flush=True)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "archive": self.archive,
            "threads_total": self.threads_total,
            "threads_done": self.threads_done,
            "messages": self.messages,
            "media": self.media,
            "owner": self.owner,
            "merged": self.merged,
            "created": self.created,
            "ambiguous": self.ambiguous,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1)
            if self.started_at
            else 0,
            "log": self.log[-40:],
        }


def reset_database(conn) -> None:
    for table in (
        "thread_word_freq", "thread_emoji_freq", "thread_month_stats", "message_emoji",
        "reaction", "media", "bookmark", "message", "thread_participant", "thread",
        "person", "import_archive", "import_source",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("INSERT INTO message_fts(message_fts) VALUES('rebuild')")
    conn.commit()


def purge_conversations(note: Callable[[str], None]) -> int:
    """Delete the unpacked archives so a reset really starts from nothing.

    Clearing the database alone would not do it: the importer reads the whole
    shared export root, so every old conversation would reappear on the next
    run.

    This directory now lives *inside* DATA_DIR, next to the database and the
    thumbnail cache, so the scope is deliberately narrow: only directories
    directly under it, never symlinks, and never DATA_DIR itself.
    """
    conversations = db.conversations_dir()
    if not conversations.is_dir():
        return 0
    if conversations.resolve() == db.data_dir().resolve():
        raise RuntimeError("Refusing to purge DATA_DIR itself")

    removed = 0
    for entry in sorted(conversations.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        note(f"  removing unpacked archive {entry.name}")
        shutil.rmtree(entry)
        removed += 1
    return removed


def _parse_secure(conn, matcher: ThreadMatcher, path: Path, progress: ImportProgress):
    """Decide which conversation an encrypted thread belongs to, then read it."""
    participants, title, first_ts, _last_ts = read_participants(path)
    result = matcher.match(participants, title, first_ts, fallback_key=f"secure:{path.stem}")

    if result.reason == "merged":
        progress.merged += 1
    elif result.reason == "ambiguous":
        progress.ambiguous += 1
        progress.note(
            f"  '{title}' matches several existing conversations — keeping it separate"
        )
    else:
        progress.created += 1

    return parse_secure_thread(path, result.thread_key, result.source)


def import_sources(
    sources: Sequence[Path | str],
    *,
    reset: bool = False,
    owner: str | None = None,
    delete_zips: bool = False,
    progress: ImportProgress | None = None,
    on_update: Callable[[ImportProgress], None] | None = None,
) -> ImportProgress:
    """Import one or more archives, then derive indexes once over the merged result.

    Facebook splits a long history across several zips, so all of them are loaded
    before ``derive.run_all`` runs — otherwise ``seq`` would be recomputed per
    archive and the last one would win.
    """
    progress = progress or ImportProgress()
    progress.state = "running"
    progress.started_at = time.time()

    conn = db.connect()
    db.apply_schema(conn)

    try:
        if reset:
            # Must happen before unpacking, since the new archives land in the
            # very directory being cleared.
            progress.note("Starting over: clearing database and unpacked archives …")
            reset_database(conn)
            removed = purge_conversations(progress.note)
            progress.note(f"  removed {removed} unpacked archive(s)")

        extract_dir = db.conversations_dir()
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Unpack everything before reading anything: one archive holds the JSON
        # and the others hold the photos it references, so the tree is only
        # complete once every part has landed in the shared root.
        progress.state = "unpacking"
        if on_update:
            on_update(progress)
        exports = reader.resolve_sources(
            [Path(s) for s in sources],
            extract_dir,
            delete_zip_after_extract=delete_zips,
            on_note=progress.note,
        )

        for export in exports:
            progress.state = "running"
            progress.archive = export.archive_name
            progress.note(f"Importing {export.archive_name} (root: {export.root})")

            threads = (
                list(iter_secure_threads(export.messages_dir))
                if export.format == reader.FORMAT_SECURE
                else list(reader.iter_threads(export))
            )
            progress.threads_total += len(threads)
            progress.note(f"  found {len(threads)} conversations ({export.format} format)")

            people = load.PersonCache(conn)
            source_id = load.upsert_import_source(
                conn, export.archive_name, export.root, int(time.time())
            )
            load.record_archives(conn, source_id, export.archives, int(time.time()))

            matcher = (
                ThreadMatcher(conn) if export.format == reader.FORMAT_SECURE else None
            )

            source_messages = 0
            for index, entry in enumerate(threads, start=1):
                if matcher is None:
                    parsed = parse_thread(entry)
                else:
                    parsed = _parse_secure(conn, matcher, entry, progress)

                thread_id = load.upsert_thread(conn, people, parsed)
                if matcher is not None:
                    matcher.remember(
                        parsed.participants,
                        Candidate(thread_id, parsed.thread_key, parsed.title, parsed.source, None),
                    )

                written = load.load_messages(
                    conn, people, parsed, thread_id, source_id, export.root
                )
                source_messages += written
                progress.threads_done += 1
                progress.messages += written

                if index % 25 == 0 or index == len(threads):
                    conn.commit()
                    progress.note(
                        f"  {index}/{len(threads)} conversations, {progress.messages} messages"
                    )
                    if on_update:
                        on_update(progress)

            if matcher is not None:
                progress.note(
                    f"  stitched onto existing history: {progress.merged} merged, "
                    f"{progress.created} new, {progress.ambiguous} kept separate (ambiguous)"
                )

            conn.commit()
            conn.execute(
                "UPDATE import_source SET thread_count = ?, message_count = ? WHERE id = ?",
                (len(threads), source_messages, source_id),
            )
            conn.commit()

        progress.state = "deriving"
        progress.note("Building indexes (seq, full-text, statistics) …")
        if on_update:
            on_update(progress)

        progress.owner = derive.run_all(conn, owner)
        progress.media = conn.execute("SELECT count(*) FROM media").fetchone()[0]
        progress.messages = conn.execute("SELECT count(*) FROM message").fetchone()[0]

        progress.state = "done"
        progress.finished_at = time.time()
        progress.note(
            f"Done: {progress.messages} messages, {progress.media} media files, "
            f"owner detected as {progress.owner!r} "
            f"({progress.finished_at - progress.started_at:.1f}s)"
        )
    except Exception as exc:  # surfaced to the UI, and re-raised for the CLI
        conn.rollback()
        progress.state = "error"
        progress.error = f"{type(exc).__name__}: {exc}"
        progress.finished_at = time.time()
        progress.note(f"Import failed: {progress.error}")
        if on_update:
            on_update(progress)
        raise
    finally:
        conn.close()

    if on_update:
        on_update(progress)
    return progress
