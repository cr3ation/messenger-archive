# Messenger Archive

A local web app that makes a Facebook Messenger export readable: it imports the export into SQLite
with FTS5 and presents it as a modern chat app — full-text search, timeline navigation, a media
gallery, per-conversation statistics and bookmarks.

Built for real archives: 400,000 messages spanning 19 years, single conversations with 60,000
messages, tens of thousands of photos. It handles both formats Messenger produces — "Download your
information" and the encrypted chat export — and stitches them into one continuous timeline per
conversation.

Everything runs in Docker. Nothing is installed on the host.

> **Your data never leaves the machine and is never versioned.** The whole `data/` directory — the
> database, the unpacked originals and the thumbnail cache — is gitignored. This repository
> contains code only.

---

## Getting started

```bash
make up
```

Open **http://localhost:5183**. On first run a setup wizard appears: drop in your zip files and
they are uploaded, unpacked and imported.

> Facebook splits the export across several zip files — **one holds the text, the others hold the
> photos**. Select them all at once. Picking only some leaves you with an incomplete history or
> broken images.

Ports are configurable: `API_PORT=8010 WEB_PORT=5183 make up`.

### Adding more archives, or starting over

Reopen the wizard from `+` in the toolbar. If an archive is already imported you get a choice:

- **Add to the current archive** — new content is added, duplicates are merged, bookmarks survive.
- **Start over from scratch** — deletes the database **and the unpacked originals in
  `./data/imported-conversations/`**. Clearing only the database is not enough: the importer reads
  the whole directory, so everything old would come straight back. It requires an explicit
  confirmation, and the files cannot be recovered without downloading the export from Facebook
  again. `python -m app.importer --reset` behaves the same way.

### Shortcut for large archives

Export zips are often several gigabytes. If they already sit in the project directory you can skip
the upload:

```bash
make import-all                                    # every *.zip in the project root
make import SRC="/host/part1.zip /host/part2.zip"  # specific files
make import SRC=/host/your_facebook_activity       # an already-unpacked folder
```

`/host` is the project directory mounted read-only inside the container. Files read from there are
never deleted — only archives uploaded through the wizard are cleaned up after unpacking.

### Production mode

```bash
make prod     # a single container on http://localhost:8010
```

---

## Where things live

Everything the app owns sits under `./data/`:

| Path | Contents | Disposable? |
|---|---|---|
| `data/imported-conversations/` | **The originals.** Photos, videos, audio, PDFs and the source JSON. All media is served from here. | **No — this is what you back up** |
| `data/archive.db` | All text: messages, search index, statistics, bookmarks | Yes, rebuilt on re-import |
| `data/thumbs/` | Generated WebP thumbnails | Yes, regenerated on demand |
| `data/uploads/` | Zips being uploaded | Cleared automatically |

The database stores paths, never image bytes. `make clean-db` touches only the database files and
never your originals — but deleting all of `./data/` takes the photos with it.

---

## How it works

### The character encoding

Facebook's JSON escapes each **byte** as its own `\uXXXX` codepoint, so `Engström` arrives as
`EngstrÃ¶m`. [`encoding.py`](apps/backend/app/encoding.py) reverses it with
`s.encode('latin-1').decode('utf-8')` — but only when the round trip decodes cleanly end to end,
because otherwise correct Swedish text like `Allmän` would be destroyed. Tests pin down both
directions.

### Two export formats

Messenger delivers your history in two entirely different formats, and the app accepts both:

- **Download your information** — `your_facebook_activity/`, one folder per conversation. Covers
  everything up to the day that chat was encrypted.
- **Encrypted chat export** — a flat `<Name>_<n>.json` per conversation plus a shared `media/`
  folder. The only place messages sent after encryption exist.

The format is detected from the zip's index, and each unpacks into its own root. Conversations are
then matched on their participant set, so a chat becomes one continuous timeline even though the
two halves come from different exports. When the match is ambiguous — two chats with the same
person, or a thread whose other party is unknown — a separate thread is created rather than
guessing wrong.

### One shared root per download

All zip parts of *a single* "Download your information" download unpack into the **same**
directory. Facebook does not split an export by date but by file: in the six-part export this was
measured on, 306 conversations had their media in a different zip from their JSON. Giving each
archive its own root would have made every one of them unreadable.

### Jumping around 58,000 messages

Every message is assigned a `seq` — its absolute position within the thread — at import time. The
frontend knows the thread's length up front, so the scrollbar is correct before anything has
loaded, and jumping to "July 2014" or a search hit is a direct `scrollToIndex(seq)`. Only the pages
about to be painted are fetched. A window in the middle of the largest thread responds in ~17 ms.

The media gallery does the same: `media/locate` computes a photo's position using the same
`ORDER BY` the grid paints in, so the gallery can jump straight to photo 3,000 of 4,457. Both views
share the paging logic in [`useSparsePages`](apps/frontend/src/hooks/useSparsePages.ts).

### The gallery follows your reading position

Sitting in July 2017 in a conversation, the gallery shows what was shared then. The chat view
reports the timestamp of the topmost visible message, the gallery looks up the nearest photo via
`media/locate?ts=` and scrolls there. Following pauses for four seconds as soon as you scroll the
gallery yourself — otherwise the two fight over the scroll position. A chip in the gallery header
shows which mode is active and turns following off entirely if you want.

### Search ordering

Searching for a person should surface that person, not every group they happened to be in. Direct
conversations therefore rank first, then groups whose name matches, then groups where a participant
matches; recency only breaks ties within a rank. Your own membership does not count — you are in
every single thread, so without that exception a search for your own name would return the whole
archive.

### Emoji

FTS5's `unicode61` tokenizer treats emoji as separators and never indexes them. Emoji therefore get
an index of their own, which also drives the "most used emoji" statistic. `❤` and `❤️` are
normalised to the same character; otherwise search misses half the hits.

### Search hits cannot inject markup

`snippet()` returns invisible sentinel characters instead of `<mark>`. The frontend splits on them
and renders the pieces as text nodes — 19 years of chat content never reaches the DOM as HTML.

### Re-importing and adding archives

Every message gets a `dedupe_key` derived from its content. Re-importing the same export, or adding
next year's, converges instead of duplicating — and `message.id` stays put, so bookmarks still
point at the right message afterwards.

---

## Development

```bash
make test      # 105 pytest tests
make shell     # a shell in the api container
make db        # row counts from the database
make clean-db  # delete the database (your originals are untouched)
```

Layout:

```
apps/backend/app/
├── encoding.py  emoji.py  db.py  schema.sql  deps.py
├── importer/    reader → parse → load → derive
└── routers/     threads  search  media  stats  bookmarks  admin

apps/frontend/src/
├── components/  Sidebar  ChatView  MessageBubble  SearchPanel  TimeTravel
│                MediaGallery  Lightbox  StatsDialog  BookmarksPanel  SetupWizard
└── hooks/       useThreadWindow  useSparsePages
```

## Keyboard

| Key | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Open search |
| `Esc` | Close panel or lightbox |
| `←` `→` | Step through the lightbox |

## License

MIT — see [LICENSE](LICENSE).
