"""Archive state, zip uploads and running imports from the setup wizard."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import db
from ..deps import get_db
from ..importer import ImportProgress, import_sources

router = APIRouter(prefix="/api", tags=["admin"])

_progress = ImportProgress()
_lock = threading.Lock()

UPLOAD_CHUNK = 1024 * 1024      # 1 MiB — an 800 MB archive never lands in memory
ZIP_MAGIC = b"PK\x03\x04"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def host_dir() -> Path:
    return Path(os.environ.get("HOST_DIR", "/host"))


def safe_upload_name(filename: str) -> str:
    """Reduce a client-supplied filename to a bare, safe `.zip` basename."""
    base = Path(filename).name  # strips any directory component
    base = _SAFE_NAME_RE.sub("_", base).lstrip(".")
    if not base.lower().endswith(".zip"):
        raise HTTPException(400, "Only .zip archives can be uploaded")
    if len(base) < 5:
        raise HTTPException(400, "Filename is too short")
    return base


class ImportRequest(BaseModel):
    # Names previously handed to /api/admin/upload. Empty means "everything pending".
    uploads: list[str] = []
    reset: bool = False
    owner: str | None = None


@router.get("/state")
def state(conn: sqlite3.Connection = Depends(get_db)):
    counts = conn.execute(
        """SELECT (SELECT count(*) FROM thread)   AS threads,
                  (SELECT count(*) FROM message)  AS messages,
                  (SELECT count(*) FROM media)    AS media,
                  (SELECT count(*) FROM bookmark) AS bookmarks"""
    ).fetchone()
    owner = conn.execute("SELECT name FROM person WHERE is_owner = 1").fetchone()
    sources = [
        dict(row)
        for row in conn.execute(
            "SELECT source, count(*) AS n FROM thread GROUP BY source ORDER BY source"
        )
    ]
    archives = [
        dict(row)
        for row in conn.execute(
            "SELECT name AS archive_name, unpacked_at AS imported_at, file_count, size_bytes "
            "FROM import_archive ORDER BY unpacked_at DESC, name"
        )
    ]
    missing_media = conn.execute(
        "SELECT count(*) FROM media WHERE is_missing = 1"
    ).fetchone()[0]
    span = conn.execute("SELECT min(first_ts) AS a, max(last_ts) AS b FROM thread").fetchone()
    return {
        **dict(counts),
        "owner": owner["name"] if owner else None,
        "sources": sources,
        "archives": archives,
        "missing_media": missing_media,
        "first_ts": span["a"],
        "last_ts": span["b"],
        "has_data": counts["messages"] > 0,
    }


@router.get("/admin/disk")
def disk_space():
    """Free space where uploads and unpacked archives land, for the wizard's warning."""
    usage = shutil.disk_usage(db.data_dir())
    return {"free_bytes": usage.free, "total_bytes": usage.total}


@router.get("/admin/uploads")
def list_uploads():
    uploads = db.uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)
    return {
        "uploads": [
            {"name": path.name, "size_bytes": path.stat().st_size}
            for path in sorted(uploads.glob("*.zip"))
        ]
    }


@router.post("/admin/upload")
async def upload(request: Request, filename: str):
    """Stream a zip straight to disk.

    The body is read in chunks and appended to a `.part` file, so memory use is
    flat regardless of archive size.  The first chunk must carry the zip
    signature, which rejects a mistaken drag of some other file before hundreds
    of megabytes have been written.
    """
    name = safe_upload_name(filename)
    uploads = db.uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)

    target = uploads / name
    partial = uploads / f"{name}.part"
    written = 0
    checked_magic = False

    try:
        with partial.open("wb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                if not checked_magic:
                    if not chunk.startswith(ZIP_MAGIC):
                        raise HTTPException(400, "That file is not a zip archive")
                    checked_magic = True
                handle.write(chunk)
                written += len(chunk)
    except HTTPException:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        # A cancelled upload leaves a partial file behind; drop it.
        partial.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {exc}") from exc

    if written == 0:
        partial.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")

    partial.replace(target)
    return {"name": name, "size_bytes": written}


@router.delete("/admin/uploads/{name}")
def delete_upload(name: str):
    safe = safe_upload_name(name)
    uploads = db.uploads_dir()
    (uploads / safe).unlink(missing_ok=True)
    (uploads / f"{safe}.part").unlink(missing_ok=True)
    return {"name": safe, "deleted": True}


@router.get("/admin/import/status")
def import_status():
    return _progress.as_dict()


@router.post("/admin/import")
def start_import(request: ImportRequest):
    """Unpack and import uploaded archives, deleting each zip once unpacked."""
    global _progress

    with _lock:
        if _progress.state in ("unpacking", "running", "deriving"):
            raise HTTPException(409, "An import is already running")

        uploads = db.uploads_dir()
        uploads.mkdir(parents=True, exist_ok=True)

        if request.uploads:
            paths = [uploads / safe_upload_name(name) for name in request.uploads]
            missing = [p.name for p in paths if not p.is_file()]
            if missing:
                raise HTTPException(404, f"Not uploaded: {', '.join(missing)}")
        else:
            paths = sorted(uploads.glob("*.zip"))
        if not paths:
            raise HTTPException(400, "No uploaded archives to import")

        _progress = ImportProgress()
        progress = _progress

    def run() -> None:
        try:
            import_sources(
                paths,
                reset=request.reset,
                owner=request.owner,
                delete_zips=True,
                progress=progress,
            )
        except Exception:
            pass  # already recorded on the progress object

    threading.Thread(target=run, daemon=True, name="import").start()
    return progress.as_dict()
