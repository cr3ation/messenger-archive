"""API behaviour that is easy to get subtly wrong: ranking and gallery positions."""

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

OWNER = "Henrik Engström"


def mangle(text: str) -> str:
    return text.encode("utf-8").decode("latin-1")


def message(sender: str, ts: int, content: str | None = None, photo: str | None = None) -> dict:
    entry: dict = {"sender_name": mangle(sender), "timestamp_ms": ts}
    if content:
        entry["content"] = mangle(content)
    if photo:
        entry["photos"] = [{"uri": photo, "creation_timestamp": ts // 1000}]
    return entry


def build_export(root: Path, name: str = "facebook-2026-08-05-AAAA.zip") -> Path:
    """A small archive with one DM and two groups, all involving an 'Erika'.

    Names mimic Facebook's: parts of one download share everything but the
    trailing random token, which is what groups them into a shared root.
    """
    zip_path = root / name
    base = "your_facebook_activity/messages/inbox"

    def thread(key: str, title: str, people: list[str], messages: list[dict]) -> tuple[str, str]:
        return (
            f"{base}/{key}/message_1.json",
            json.dumps(
                {
                    "participants": [{"name": mangle(p)} for p in people],
                    "title": mangle(title),
                    "is_still_participant": True,
                    "thread_path": f"inbox/{key}",
                    "messages": messages,
                }
            ),
        )

    photos = [f"{base}/erikakarlestedt_1/photos/p{i}.jpg" for i in range(5)]

    entries = [
        # Direct conversation, oldest activity of the three.
        thread(
            "erikakarlestedt_1",
            "Erika Karlestedt",
            [OWNER, "Erika Karlestedt"],
            [
                message("Erika Karlestedt", 1_000_000_000_000, "hello there"),
                *[
                    message(OWNER, 1_000_000_100_000 + i * 86_400_000, photo=photos[i])
                    for i in range(5)
                ],
            ],
        ),
        # Group whose *title* contains Erika, more recent.
        thread(
            "erikaochfelicia_2",
            "Erika och Felicia",
            [OWNER, "Erika Karlestedt", "Felicia Berg"],
            [message("Felicia Berg", 2_000_000_000_000, "vi ses")],
        ),
        # Group where Erika is only a participant, most recent of all.
        thread(
            "midsommar_3",
            "Midsommar 2026",
            [OWNER, "Erika Karlestedt", "Felicia Berg"],
            [message("Felicia Berg", 3_000_000_000_000, "sill och potatis")],
        ),
    ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, payload in entries:
            zf.writestr(name, payload)
        for photo in photos:
            zf.writestr(photo, b"\xff\xd8\xff\xe0 fake jpeg")

    return zip_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ARCHIVE_DB", str(data / "archive.db"))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("CONVERSATIONS_DIR", raising=False)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "no-static"))

    from app.importer import import_sources

    import_sources([build_export(tmp_path)], reset=True)

    from app import db
    from app.main import app

    with TestClient(app) as test_client:
        test_client.exports = db.conversations_dir()  # type: ignore[attr-defined]
        yield test_client


def titles(payload: dict) -> list[str]:
    return [thread["title"] for thread in payload["threads"]]


def test_direct_conversations_rank_above_groups(client):
    """Searching a person's name must surface the person, not every group they were in."""
    payload = client.get("/api/threads", params={"q": "erika", "sources": "inbox"}).json()

    assert titles(payload)[0] == "Erika Karlestedt"
    ranks = [thread["match_rank"] for thread in payload["threads"]]
    assert ranks == sorted(ranks)
    # Group named after Erika outranks the one where she is merely a member.
    assert titles(payload).index("Erika och Felicia") < titles(payload).index("Midsommar 2026")


def test_recency_still_orders_within_a_rank(client):
    """Without a query the list is purely most-recent-first, as before."""
    payload = client.get("/api/threads", params={"sources": "inbox"}).json()
    assert titles(payload) == ["Midsommar 2026", "Erika och Felicia", "Erika Karlestedt"]


def test_searching_your_own_name_does_not_match_everything(client):
    """You are a participant in every thread; matching yourself would list them all."""
    payload = client.get("/api/threads", params={"q": "Henrik", "sources": "inbox"}).json()
    assert payload["threads"] == []


def test_group_still_found_by_member_name(client):
    payload = client.get("/api/threads", params={"q": "Felicia", "sources": "inbox"}).json()
    assert "Midsommar 2026" in titles(payload)


def _thread_id(client, title: str) -> int:
    payload = client.get("/api/threads", params={"sources": "inbox"}).json()
    return next(t["id"] for t in payload["threads"] if t["title"] == title)


def test_media_listing_reports_total(client):
    thread_id = _thread_id(client, "Erika Karlestedt")
    payload = client.get(f"/api/threads/{thread_id}/media", params={"limit": 2}).json()
    assert payload["total"] == 5
    assert len(payload["items"]) == 2


def test_locate_media_by_id_matches_listing_order(client):
    """The offset must address the same slot the gallery paints, or jumps land wrong."""
    thread_id = _thread_id(client, "Erika Karlestedt")
    items = client.get(f"/api/threads/{thread_id}/media", params={"limit": 100}).json()["items"]

    for expected_offset, item in enumerate(items):
        found = client.get(
            f"/api/threads/{thread_id}/media/locate", params={"media_id": item["id"]}
        ).json()
        assert found["offset"] == expected_offset


def test_locate_media_by_timestamp_lands_at_or_before(client):
    thread_id = _thread_id(client, "Erika Karlestedt")
    items = client.get(f"/api/threads/{thread_id}/media", params={"limit": 100}).json()["items"]
    middle = items[2]

    found = client.get(
        f"/api/threads/{thread_id}/media/locate", params={"ts": middle["ts"]}
    ).json()
    assert found["offset"] == 2
    assert found["ts"] <= middle["ts"]


def test_locate_media_before_anything_shared_returns_oldest(client):
    thread_id = _thread_id(client, "Erika Karlestedt")
    found = client.get(f"/api/threads/{thread_id}/media/locate", params={"ts": 1}).json()
    assert found["offset"] == 4  # five photos, newest first


def test_media_timeline_offsets_point_at_that_month(client):
    thread_id = _thread_id(client, "Erika Karlestedt")
    months = client.get(f"/api/threads/{thread_id}/media/timeline").json()["months"]
    items = client.get(f"/api/threads/{thread_id}/media", params={"limit": 100}).json()["items"]

    assert months
    for month in months:
        item = items[month["offset"]]
        assert month["ym"] == __import__("datetime").datetime.fromtimestamp(
            item["ts"] / 1000, __import__("datetime").UTC
        ).strftime("%Y-%m")


def test_locate_media_requires_a_target(client):
    thread_id = _thread_id(client, "Erika Karlestedt")
    assert client.get(f"/api/threads/{thread_id}/media/locate").status_code == 400


def later_download(tmp_path: Path) -> Path:
    """A download made on another date — a different prefix, so a separate root."""
    folder = tmp_path / "later"
    folder.mkdir(exist_ok=True)
    return build_export(folder, "facebook-2027-01-01-ZZZZ.zip")


def test_reset_clears_unpacked_archives(client, tmp_path):
    """Starting over must delete the files too — the importer reads the whole root."""
    from app.importer import import_sources

    exports = client.exports  # type: ignore[attr-defined]
    assert [entry.name for entry in exports.iterdir() if entry.is_dir()] == ["facebook-2026-08-05"]

    import_sources([later_download(tmp_path)], reset=True)

    roots = [entry.name for entry in exports.iterdir() if entry.is_dir()]
    assert roots == ["facebook-2027-01-01"]


def test_add_mode_keeps_existing_archives(client, tmp_path):
    from app.importer import import_sources

    exports = client.exports  # type: ignore[attr-defined]
    import_sources([later_download(tmp_path)], reset=False)

    roots = sorted(entry.name for entry in exports.iterdir() if entry.is_dir())
    assert roots == ["facebook-2026-08-05", "facebook-2027-01-01"]


def test_parts_of_one_download_share_a_root(client, tmp_path):
    """The whole point: JSON in one part, photos in another, one root for both."""
    from app.importer import import_sources

    exports = client.exports  # type: ignore[attr-defined]
    folder = tmp_path / "sibling"
    folder.mkdir()
    sibling = build_export(folder, "facebook-2026-08-05-BBBB.zip")

    import_sources([sibling], reset=False)

    roots = [entry.name for entry in exports.iterdir() if entry.is_dir()]
    assert roots == ["facebook-2026-08-05"]


def test_reset_never_touches_the_database(client, tmp_path):
    from app.importer.runner import purge_conversations

    exports = client.exports  # type: ignore[attr-defined]
    bystander = tmp_path / "data" / "archive.db"
    assert bystander.exists()

    purge_conversations(lambda _line: None)

    assert bystander.exists()
    assert list(exports.iterdir()) == []
