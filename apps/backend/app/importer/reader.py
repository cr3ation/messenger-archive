"""Locating and unpacking a Facebook export.

An export can be handed to us in three shapes and all of them have to end up
pointing at the same place:

  * ``facebook-....zip``                        → unpacked into the shared export root
  * ``.../your_facebook_activity``              → used in place
  * ``.../your_facebook_activity/messages``     → used in place

``export_root`` is the directory that media URIs inside the JSON are relative
to.  Those URIs look like ``your_facebook_activity/messages/inbox/<t>/photos/x.jpg``,
so the root is always the *parent* of ``your_facebook_activity``.

**Every zip of a download unpacks into one shared root.**  Facebook does not
split an export by date — it splits it by file, so one archive carries all the
``message_*.json`` and the others carry the photos those files point at.  In the
real 6-part export this was measured on, 306 conversations had their media in a
different zip from their JSON.  Giving each archive its own root would leave
every one of those images unresolvable.

The unpacked tree is permanent: every photo, video and PDF the app ever shows is
read from it.  Only the zip is disposable, and only when it was uploaded through
the setup wizard — a zip read from the read-only host mount is never touched.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

# Two unrelated export formats end up here:
#
#   dyi     Facebook's "Download your information" — your_facebook_activity/…,
#           one folder per conversation, split across several zips by *file*.
#   secure  Messenger's end-to-end-encrypted chat export — one flat
#           "<Name>_<n>.json" per conversation plus a shared media/ folder.
#           This is the only place post-encryption messages exist.
FORMAT_DYI = "dyi"
FORMAT_SECURE = "secure"

# Folders under `messages/` that hold conversations.  Ordered so that the
# interesting ones are imported first when progress is being watched.
THREAD_SOURCES = (
    "inbox",
    "e2ee_cutover",
    "archived_threads",
    "message_requests",
    "filtered_threads",
)


@dataclass
class UnpackedArchive:
    name: str
    file_count: int
    size_bytes: int | None


@dataclass
class ExportRoot:
    archive_name: str                 # name of the root folder, not of any one zip
    root: Path                        # media URIs resolve against this
    messages_dir: Path                # DYI: <root>/your_facebook_activity/messages; secure: <root>
    archives: list[UnpackedArchive] = field(default_factory=list)
    format: str = FORMAT_DYI          # dyi | secure


@dataclass(frozen=True)
class ThreadFiles:
    thread_key: str      # folder name, unique per conversation
    source: str          # inbox | filtered_threads | ...
    directory: Path
    files: list[Path]    # message_1.json, message_2.json, ... in numeric order


class ExportNotFound(Exception):
    pass


def _find_messages_dir(base: Path) -> Path:
    """Find the `messages` directory no matter which level we were pointed at."""
    if base.name == "messages" and base.is_dir():
        return base

    direct = base / "your_facebook_activity" / "messages"
    if direct.is_dir():
        return direct

    if (base / "messages").is_dir():
        return base / "messages"

    # Zips occasionally nest everything one level deeper than documented.
    for candidate in sorted(base.glob("*/your_facebook_activity/messages")):
        if candidate.is_dir():
            return candidate

    raise ExportNotFound(
        f"Could not find a 'your_facebook_activity/messages' directory under {base}"
    )


def _safe_extract(
    zip_path: Path,
    target: Path,
    note: Callable[[str], None],
) -> int:
    """Extract *zip_path* into *target*, refusing members that escape it.

    Members already present at the right size are skipped, which makes a
    re-import of a 14 GB download cheap instead of a full re-extraction.
    """
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    written = 0

    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]

        for member in members:
            destination = (target / member.filename).resolve()
            if not destination.is_relative_to(resolved_target):
                raise ValueError(f"Refusing to extract outside target: {member.filename}")

        total = len(members)
        for index, member in enumerate(members, start=1):
            destination = target / member.filename
            if destination.exists() and destination.stat().st_size == member.file_size:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, destination.open("wb") as dst:
                while chunk := src.read(1024 * 512):
                    dst.write(chunk)
            written += 1
            if written % 500 == 0:
                note(f"    {index}/{total} files …")

    return written


def classify_zip(zip_path: Path) -> str:
    """Tell the two export formats apart from the archive index alone."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if any(name.startswith("your_facebook_activity/") for name in names):
            return FORMAT_DYI
        for name in names:
            if "/" not in name and name.endswith(".json"):
                try:
                    head = json.loads(zf.read(name))
                except (ValueError, KeyError):
                    continue
                if isinstance(head, dict) and "threadName" in head:
                    return FORMAT_SECURE
    raise ExportNotFound(f"{zip_path.name} is not a Messenger export I recognise")


def classify_folder(folder: Path) -> str:
    if (folder / "your_facebook_activity").is_dir() or folder.name in ("messages", "your_facebook_activity"):
        return FORMAT_DYI
    if any(p.suffix == ".json" for p in folder.glob("*.json")):
        return FORMAT_SECURE
    return FORMAT_DYI


def archive_set_name(sources: Iterable[Path]) -> str:
    """Name the shared root after what the archives have in common.

    Facebook names the parts of one download identically apart from a random
    suffix (``facebook-cr3ation-2026-08-05-Ki9KTCZR``), so the common prefix is a
    meaningful folder name.  Falls back to ``facebook`` when there is nothing to
    agree on.
    """
    stems = [Path(s).stem for s in sources if Path(s).suffix.lower() == ".zip"]
    if not stems:
        return "facebook"
    if len(stems) == 1:
        return stems[0].rsplit("-", 1)[0] or stems[0]

    prefix = os.path.commonprefix(stems).rstrip("-_ ")
    return prefix or "facebook"


def resolve_sources(
    sources: Iterable[Path],
    conversations_dir: Path,
    *,
    delete_zip_after_extract: bool = False,
    on_note: Callable[[str], None] | None = None,
) -> list[ExportRoot]:
    """Unpack and locate every source, grouped by export format.

    The parts of one "Download your information" download must share a root,
    because Facebook splits it by file: one part carries the JSON and the others
    carry the photos it references. A secure-storage archive is self-contained
    and gets its own root — mixing the two would leave the DYI locator hunting
    for a `your_facebook_activity` directory among loose JSON files.

    ``delete_zip_after_extract`` removes each archive once it has been unpacked
    successfully — used for zips uploaded through the wizard, which are only a
    transport format.  If extraction fails the zip is kept so the unpack can be
    retried without re-uploading several gigabytes.
    """
    note = on_note or (lambda line: print(line, flush=True))
    sources = [Path(s) for s in sources]

    for source in sources:
        if not source.exists():
            raise ExportNotFound(f"No such path: {source}")

    zips = [s for s in sources if s.is_file() and s.suffix.lower() == ".zip"]
    folders = [s for s in sources if s not in zips]
    roots: list[ExportRoot] = []

    def unpack(source: Path, target: Path) -> UnpackedArchive:
        size = source.stat().st_size
        note(f"  unpacking {source.name} ({size / 1e9:.2f} GB) → {target} …")
        count = _safe_extract(source, target, note)
        note(f"  unpacked {count} new files from {source.name}")
        if delete_zip_after_extract:
            source.unlink(missing_ok=True)
            note(f"  removed uploaded archive {source.name}")
        return UnpackedArchive(source.name, count, size)

    by_format: dict[str, list[Path]] = {}
    for source in zips:
        by_format.setdefault(classify_zip(source), []).append(source)

    dyi_zips = by_format.get(FORMAT_DYI, [])
    if dyi_zips:
        target = conversations_dir / archive_set_name(dyi_zips)
        unpacked = [unpack(source, target) for source in dyi_zips]
        messages_dir = _find_messages_dir(target)
        roots.append(
            ExportRoot(
                archive_name=target.name,
                root=messages_dir.parent.parent,
                messages_dir=messages_dir,
                archives=unpacked,
                format=FORMAT_DYI,
            )
        )

    for source in by_format.get(FORMAT_SECURE, []):
        target = conversations_dir / source.stem
        unpacked = [unpack(source, target)]
        roots.append(
            ExportRoot(
                archive_name=target.name,
                root=target,           # media URIs are relative to the archive root
                messages_dir=target,   # the conversation JSON sits at the top level
                archives=unpacked,
                format=FORMAT_SECURE,
            )
        )

    for folder in folders:
        if classify_folder(folder) == FORMAT_SECURE:
            roots.append(
                ExportRoot(
                    archive_name=folder.name,
                    root=folder,
                    messages_dir=folder,
                    archives=[UnpackedArchive(folder.name, 0, None)],
                    format=FORMAT_SECURE,
                )
            )
            continue

        messages_dir = _find_messages_dir(folder)
        name = folder.name if folder.name != "messages" else folder.parent.name
        roots.append(
            ExportRoot(
                archive_name=name,
                root=messages_dir.parent.parent,
                messages_dir=messages_dir,
                archives=[UnpackedArchive(name, 0, None)],
                format=FORMAT_DYI,
            )
        )

    # Order matters, not just grouping: encrypted history is stitched onto the
    # conversation it continues, so that conversation has to be in the database
    # first. Otherwise every chat would be imported twice — once per format.
    roots.sort(key=lambda root: root.format != FORMAT_DYI)
    return roots


def _file_order(path: Path) -> tuple[int, str]:
    stem = path.stem  # message_12
    _, _, number = stem.partition("_")
    return (int(number) if number.isdigit() else 0, stem)


def iter_threads(export: ExportRoot) -> Iterator[ThreadFiles]:
    """Yield every conversation folder that contains at least one message file."""
    for source in THREAD_SOURCES:
        source_dir = export.messages_dir / source
        if not source_dir.is_dir():
            continue
        for directory in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            files = sorted(directory.glob("message_*.json"), key=_file_order)
            if files:
                yield ThreadFiles(
                    thread_key=directory.name,
                    source=source,
                    directory=directory,
                    files=files,
                )


def count_threads(export: ExportRoot) -> int:
    return sum(1 for _ in iter_threads(export))
