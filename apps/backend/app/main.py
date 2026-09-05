"""FastAPI entrypoint: API routers, plus the built SPA when running in production."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routers import admin, bookmarks, media, search, stats, threads


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the database (and its tables) up front so a fresh checkout can
    # serve the "no data yet, import an export" state instead of erroring.
    conn = db.connect()
    db.apply_schema(conn)
    conn.close()
    yield


app = FastAPI(title="Messenger Archive", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(threads.router)
app.include_router(search.router)
app.include_router(stats.router)
app.include_router(bookmarks.router)
app.include_router(admin.router)
app.include_router(media.router)


@app.get("/api/health")
def health():
    return {"ok": True, "db": str(db.db_path())}


static_dir = Path(os.environ.get("STATIC_DIR", "/srv/static"))
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
