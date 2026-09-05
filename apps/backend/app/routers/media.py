"""Serving the export's own files: originals (with range support) and thumbnails."""

from __future__ import annotations

import mimetypes
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import db
from ..deps import get_db

router = APIRouter(tags=["media"])

THUMBABLE = {"photo", "gif", "sticker"}
THUMB_SIZES = (160, 320, 640)
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK = 1024 * 256


def _resolve(conn: sqlite3.Connection, media_id: int) -> tuple[Path, str, str]:
    """Look up a media row and return its verified absolute path.

    The client only ever sends a numeric id; the path comes from the database
    and is checked to be inside the export root it belongs to, so a crafted
    request cannot walk out of the archive.
    """
    row = conn.execute(
        """SELECT md.uri, md.kind, md.filename, s.export_root
             FROM media md JOIN import_source s ON s.id = md.source_id
            WHERE md.id = ?""",
        (media_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "No such media")

    root = Path(row["export_root"]).resolve()
    path = (root / row["uri"]).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(403, "Path escapes the export root")
    if not path.is_file():
        raise HTTPException(404, "File missing from the export")
    return path, row["kind"], row["filename"] or path.name


def _stream_range(path: Path, start: int, end: int):
    with path.open("rb") as fh:
        fh.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            block = fh.read(min(CHUNK, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


@router.get("/media/{media_id}")
def get_media(
    media_id: int,
    request: Request,
    download: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
):
    path, _kind, filename = _resolve(conn, media_id)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=31536000",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
    }

    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers=headers)

    # Audio and video seeking depends on honouring Range properly.
    match = RANGE_RE.match(range_header)
    if not match:
        return FileResponse(path, media_type=media_type, headers=headers)

    raw_start, raw_end = match.groups()
    if raw_start:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    else:  # suffix range: last N bytes
        start = max(0, size - int(raw_end or 0))
        end = size - 1
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))

    headers |= {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(
        _stream_range(path, start, end), status_code=206, media_type=media_type, headers=headers
    )


@router.get("/thumb/{media_id}")
def get_thumb(media_id: int, w: int = 320, conn: sqlite3.Connection = Depends(get_db)):
    """Downscaled WebP for the gallery grid, generated once and cached on disk."""
    width = min(THUMB_SIZES, key=lambda candidate: abs(candidate - w))
    path, kind, _filename = _resolve(conn, media_id)
    if kind not in THUMBABLE:
        raise HTTPException(415, "No thumbnail for this media type")

    cache_path = db.data_dir() / "thumbs" / str(width) / f"{media_id}.webp"
    headers = {"Cache-Control": "private, max-age=31536000"}

    if not cache_path.exists():
        from PIL import Image, ImageOps

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                image.thumbnail((width, width * 3), Image.LANCZOS)
                temporary = cache_path.with_suffix(".tmp")
                image.save(temporary, "WEBP", quality=82, method=4)
                temporary.replace(cache_path)
        except Exception:
            # Corrupt or unsupported image: fall back to the original so the
            # gallery still shows something.
            return FileResponse(path, headers=headers)

    return FileResponse(cache_path, media_type="image/webp", headers=headers)


@router.get("/media/{media_id}/meta")
def media_meta(media_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        """SELECT md.id, md.kind, md.filename, md.ts, md.size_bytes, md.message_id,
                  m.seq, m.thread_id, t.title AS thread_title, p.name AS sender
             FROM media md
             JOIN message m ON m.id = md.message_id
             JOIN thread t ON t.id = m.thread_id
             JOIN person p ON p.id = m.sender_id
            WHERE md.id = ?""",
        (media_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "No such media")
    return dict(row)


@router.head("/media/{media_id}")
def head_media(media_id: int, conn: sqlite3.Connection = Depends(get_db)):
    path, _kind, filename = _resolve(conn, media_id)
    return Response(
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(path.stat().st_size),
            "Content-Type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
        }
    )
