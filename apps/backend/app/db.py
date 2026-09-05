"""SQLite connection handling and schema bootstrap."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    return Path(os.environ.get("ARCHIVE_DB", "/data/archive.db"))


def data_dir() -> Path:
    """Everything the app stores on disk."""
    return Path(os.environ.get("DATA_DIR", "/data"))


def conversations_dir() -> Path:
    """The unpacked archives — originals the app serves media from.

    The only part of DATA_DIR that cannot be rebuilt: the database holds paths,
    never image bytes, so losing this directory breaks every photo in the app.
    """
    return Path(os.environ.get("CONVERSATIONS_DIR", str(data_dir() / "imported-conversations")))


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def connect(readonly: bool = False) -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if readonly and path.exists():
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    # SQLite's built-in lower() only folds ASCII, which would make sidebar search
    # miss "Ängen" when you type "ängen".  Python's str.lower is Unicode-aware.
    conn.create_function("ulower", 1, lambda s: s.lower() if isinstance(s, str) else s,
                         deterministic=True)
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()



def init_db() -> sqlite3.Connection:
    conn = connect()
    apply_schema(conn)
    return conn


def has_data(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT count(*) AS n FROM sqlite_master WHERE type='table' AND name='message'"
    ).fetchone()
    if not row or not row["n"]:
        return False
    return conn.execute("SELECT EXISTS(SELECT 1 FROM message)").fetchone()[0] == 1
