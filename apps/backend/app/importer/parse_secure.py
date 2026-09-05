"""Parse Messenger's end-to-end-encrypted chat export.

This is a different animal from the "Download your information" export handled
in :mod:`parse`:

  * one flat ``<Name>_<n>.json`` per conversation, no per-thread folders
  * media in a single shared ``media/`` directory, named by UUID
  * timestamps already in milliseconds, participants as plain strings
  * **already correctly encoded** — no mojibake to undo

It is also the only place messages sent after a chat was encrypted exist at all;
Facebook's own export stops dead at the cut-over date.

Everything is normalised into the same :class:`ParsedThread` shape the DYI parser
produces, so loading, indexing and statistics never learn that a second format
exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..encoding import repair_text
from .parse import MediaRef, ParsedMessage, ParsedThread, _dedupe_key

# "Adam Wistedt_28" — the trailing number is the export's file index, not part
# of the conversation's name.
_INDEX_SUFFIX = re.compile(r"_\d+$")

# Meta writes this literal string in place of a URI when its own exporter failed
# to fetch the attachment.  582 of them in the real archive: the file was never
# in the zip and never will be.
FAILED_MEDIA = "Failed to download media"

# Kind marking an attachment that never made it into the export. Deliberately
# outside GALLERY_KINDS so it cannot show up in the gallery grid.
UNAVAILABLE_KIND = "unavailable"

MEDIA_KINDS = {
    ".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".webp": "photo", ".heic": "photo",
    ".gif": "gif",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".m4a": "audio", ".aac": "audio",
}


def thread_title(thread_name: str) -> str:
    return _INDEX_SUFFIX.sub("", thread_name).strip() or thread_name


def media_kind(uri: str) -> str:
    return MEDIA_KINDS.get(Path(uri).suffix.lower(), "file")


def _parse_media(raw: dict, thread_key: str) -> list[MediaRef]:
    refs: list[MediaRef] = []
    for index, item in enumerate(raw.get("media") or []):
        uri = item.get("uri") if isinstance(item, dict) else item
        if not isinstance(uri, str) or not uri:
            continue

        if uri.strip() == FAILED_MEDIA:
            # Recorded rather than dropped: the message really did carry an
            # attachment, and saying so is more honest than a silent gap.
            # `kind` keeps it out of the gallery, `is_missing` out of the counts.
            # The URI is a sentinel, not a path — but it has to stay unique, or
            # two failed attachments on one message collide on (message_id, uri).
            refs.append(
                MediaRef(
                    kind=UNAVAILABLE_KIND,
                    uri=f"{UNAVAILABLE_KIND}:{index}",
                    filename=None,
                    creation_ts=None,
                )
            )
            continue

        relative = uri[2:] if uri.startswith("./") else uri.lstrip("/")
        refs.append(
            MediaRef(
                kind=media_kind(relative),
                uri=relative,
                filename=Path(relative).name,
                creation_ts=None,
            )
        )
    return refs


def _parse_message(raw: dict, thread_key: str) -> ParsedMessage | None:
    sender = repair_text(raw.get("senderName") or "")
    ts = raw.get("timestamp")
    if not sender or not isinstance(ts, int):
        return None

    kind = raw.get("type")
    text = raw.get("text")
    message = ParsedMessage(sender=sender, ts=ts)
    message.is_unsent = bool(raw.get("isUnsent"))

    if kind == "placeholder":
        # The text is Meta's own "User unsent a message" filler; the UI renders
        # its own wording for unsent messages, so don't store the placeholder.
        message.is_unsent = True
    elif isinstance(text, str) and text:
        message.content = repair_text(text)
        if kind == "link":
            message.share_link = message.content

    message.media = _parse_media(raw, thread_key)

    for item in raw.get("reactions") or []:
        emoji = item.get("reaction")
        actor = item.get("actor")
        if isinstance(emoji, str) and isinstance(actor, str):
            message.reactions.append((repair_text(emoji), repair_text(actor)))

    message.dedupe_key = _dedupe_key(thread_key, message)
    return message


def parse_secure_thread(path: Path, thread_key: str, source: str) -> ParsedThread:
    """Read one conversation file.

    *thread_key* is supplied by the caller because it may point at an existing
    conversation this history is being stitched onto — see
    :mod:`app.importer.match`.
    """
    with path.open("rb") as fh:
        data = json.load(fh)

    participants = [
        repair_text(name) for name in data.get("participants") or [] if isinstance(name, str)
    ]
    messages: list[ParsedMessage] = []
    seen: set[str] = set()

    for raw in data.get("messages") or []:
        parsed = _parse_message(raw, thread_key)
        if parsed and parsed.dedupe_key not in seen:
            seen.add(parsed.dedupe_key)
            messages.append(parsed)

    messages.sort(key=lambda m: m.ts)

    return ParsedThread(
        thread_key=thread_key,
        source=source,
        title=thread_title(data.get("threadName") or path.stem),
        participants=participants,
        image_uri=None,
        is_still_participant=None,
        messages=messages,
    )


def read_participants(path: Path) -> tuple[list[str], str, int | None, int | None]:
    """Cheap pre-read used to decide which existing thread this one continues."""
    with path.open("rb") as fh:
        data = json.load(fh)
    participants = [
        repair_text(name) for name in data.get("participants") or [] if isinstance(name, str)
    ]
    stamps = [m.get("timestamp") for m in data.get("messages") or [] if isinstance(m.get("timestamp"), int)]
    return (
        participants,
        thread_title(data.get("threadName") or path.stem),
        min(stamps) if stamps else None,
        max(stamps) if stamps else None,
    )


def iter_secure_threads(messages_dir: Path):
    """Yield every conversation file in a secure-storage archive."""
    for path in sorted(messages_dir.glob("*.json")):
        yield path
