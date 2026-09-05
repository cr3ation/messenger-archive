"""Turn Facebook's thread JSON into normalised records.

Every string that comes out of the JSON goes through :func:`repair_text` — see
``app.encoding`` for why Facebook's export needs it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..encoding import repair_text
from .reader import ThreadFiles

# JSON key -> media kind stored in the `media` table
MEDIA_KEYS = {
    "photos": "photo",
    "videos": "video",
    "gifs": "gif",
    "audio_files": "audio",
    "files": "file",
}


@dataclass
class MediaRef:
    kind: str
    uri: str
    filename: str
    creation_ts: int | None


@dataclass
class ParsedMessage:
    sender: str
    ts: int
    content: str | None = None
    share_link: str | None = None
    share_text: str | None = None
    sticker_uri: str | None = None
    call_duration: int | None = None
    is_unsent: bool = False
    media: list[MediaRef] = field(default_factory=list)
    reactions: list[tuple[str, str]] = field(default_factory=list)  # (emoji, actor)
    dedupe_key: str = ""


@dataclass
class ParsedThread:
    thread_key: str
    source: str
    title: str
    participants: list[str]
    image_uri: str | None
    is_still_participant: bool | None
    messages: list[ParsedMessage]

    @property
    def is_group(self) -> bool:
        return len(self.participants) > 2


def _dedupe_key(thread_key: str, message: ParsedMessage) -> str:
    """Stable identity for a message across re-imports and overlapping exports.

    Keeping this stable is what lets bookmarks survive a re-import: the row keeps
    its `message.id` because the UPSERT matches on this key.
    """
    parts = [
        thread_key,
        str(message.ts),
        message.sender,
        message.content or "",
        message.share_link or "",
        message.sticker_uri or "",
        "|".join(sorted(m.uri for m in message.media)),
    ]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _parse_message(raw: dict, thread_key: str) -> ParsedMessage | None:
    sender = repair_text(raw.get("sender_name") or "")
    ts = raw.get("timestamp_ms")
    if not sender or not isinstance(ts, int):
        return None

    message = ParsedMessage(sender=sender, ts=ts)

    content = raw.get("content")
    if isinstance(content, str) and content:
        message.content = repair_text(content)

    share = raw.get("share")
    if isinstance(share, dict):
        link = share.get("link")
        text = share.get("share_text")
        message.share_link = repair_text(link) if isinstance(link, str) else None
        message.share_text = repair_text(text) if isinstance(text, str) else None

    sticker = raw.get("sticker")
    if isinstance(sticker, dict) and isinstance(sticker.get("uri"), str):
        message.sticker_uri = sticker["uri"]

    if isinstance(raw.get("call_duration"), int):
        message.call_duration = raw["call_duration"]
    message.is_unsent = bool(raw.get("is_unsent"))

    for key, kind in MEDIA_KEYS.items():
        for item in raw.get(key) or []:
            uri = item.get("uri")
            if not isinstance(uri, str) or not uri:
                continue
            message.media.append(
                MediaRef(
                    kind=kind,
                    uri=uri,
                    filename=Path(uri).name,
                    creation_ts=item.get("creation_timestamp"),
                )
            )

    for item in raw.get("reactions") or []:
        emoji = item.get("reaction")
        actor = item.get("actor")
        if isinstance(emoji, str) and isinstance(actor, str):
            message.reactions.append((repair_text(emoji), repair_text(actor)))

    message.dedupe_key = _dedupe_key(thread_key, message)
    return message


def parse_thread(thread: ThreadFiles) -> ParsedThread:
    """Read every ``message_N.json`` in a conversation folder and merge them."""
    title = thread.thread_key
    participants: list[str] = []
    image_uri: str | None = None
    is_still_participant: bool | None = None
    messages: list[ParsedMessage] = []
    seen_keys: set[str] = set()

    for index, path in enumerate(thread.files):
        with path.open("rb") as fh:
            data = json.load(fh)

        if index == 0:
            raw_title = data.get("title")
            if isinstance(raw_title, str) and raw_title:
                title = repair_text(raw_title)
            image = data.get("image")
            if isinstance(image, dict) and isinstance(image.get("uri"), str):
                image_uri = image["uri"]
            if isinstance(data.get("is_still_participant"), bool):
                is_still_participant = data["is_still_participant"]

        for person in data.get("participants") or []:
            name = person.get("name")
            if isinstance(name, str) and name:
                repaired = repair_text(name)
                if repaired not in participants:
                    participants.append(repaired)

        for raw in data.get("messages") or []:
            parsed = _parse_message(raw, thread.thread_key)
            # A message can legitimately repeat across split files at the seam.
            if parsed and parsed.dedupe_key not in seen_keys:
                seen_keys.add(parsed.dedupe_key)
                messages.append(parsed)

    messages.sort(key=lambda m: m.ts)

    return ParsedThread(
        thread_key=thread.thread_key,
        source=thread.source,
        title=title,
        participants=participants,
        image_uri=image_uri,
        is_still_participant=is_still_participant,
        messages=messages,
    )
