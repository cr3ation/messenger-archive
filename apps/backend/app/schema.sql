-- Schema for the local Messenger archive.
-- Applied idempotently on every startup and before every import.

-- One row per *export root* — the directory media URIs resolve against.
-- Facebook splits a download into several zips arbitrarily (one holds the JSON,
-- the others hold the photos those JSON files point at), so every part is
-- unpacked into the same root and they share a single row here.
CREATE TABLE IF NOT EXISTS import_source (
  id            INTEGER PRIMARY KEY,
  archive_name  TEXT    NOT NULL UNIQUE,
  export_root   TEXT    NOT NULL,
  imported_at   INTEGER NOT NULL,
  thread_count  INTEGER DEFAULT 0,
  message_count INTEGER DEFAULT 0
);

-- One row per zip actually unpacked, for provenance in the UI.
CREATE TABLE IF NOT EXISTS import_archive (
  id          INTEGER PRIMARY KEY,
  name        TEXT    NOT NULL UNIQUE,
  source_id   INTEGER NOT NULL REFERENCES import_source(id) ON DELETE CASCADE,
  unpacked_at INTEGER NOT NULL,
  file_count  INTEGER DEFAULT 0,
  size_bytes  INTEGER
);

CREATE TABLE IF NOT EXISTS person (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL UNIQUE,      -- encoding-repaired
  is_owner INTEGER NOT NULL DEFAULT 0,
  hue      INTEGER NOT NULL DEFAULT 0    -- deterministic avatar colour derived from the name
);

CREATE TABLE IF NOT EXISTS thread (
  id                   INTEGER PRIMARY KEY,
  thread_key           TEXT    NOT NULL UNIQUE,  -- folder name, e.g. smegma_6341229605931650
  title                TEXT    NOT NULL,
  source               TEXT    NOT NULL,         -- inbox | filtered_threads | message_requests | e2ee_cutover
  is_group             INTEGER NOT NULL DEFAULT 0,
  participant_count    INTEGER NOT NULL DEFAULT 0,
  image_uri            TEXT,
  is_still_participant INTEGER,
  -- denormalised; recomputed by derive.py after each import
  first_ts      INTEGER,
  last_ts       INTEGER,
  message_count INTEGER NOT NULL DEFAULT 0,
  media_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_thread_last ON thread(source, last_ts DESC);

CREATE TABLE IF NOT EXISTS thread_participant (
  thread_id INTEGER NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES person(id),
  PRIMARY KEY (thread_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_tp_person ON thread_participant(person_id);

CREATE TABLE IF NOT EXISTS message (
  id            INTEGER PRIMARY KEY,
  thread_id     INTEGER NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
  sender_id     INTEGER NOT NULL REFERENCES person(id),
  ts            INTEGER NOT NULL,     -- timestamp_ms
  seq           INTEGER,              -- 0-based position within the thread; set by derive.py
  content       TEXT,
  share_link    TEXT,
  share_text    TEXT,
  sticker_uri   TEXT,
  call_duration INTEGER,
  is_unsent     INTEGER NOT NULL DEFAULT 0,
  has_media     INTEGER NOT NULL DEFAULT 0,
  dedupe_key    TEXT    NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_msg_thread_seq ON message(thread_id, seq);
CREATE INDEX IF NOT EXISTS idx_msg_thread_ts  ON message(thread_id, ts);
CREATE INDEX IF NOT EXISTS idx_msg_sender     ON message(sender_id);

CREATE TABLE IF NOT EXISTS media (
  id          INTEGER PRIMARY KEY,
  message_id  INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  thread_id   INTEGER NOT NULL,
  source_id   INTEGER NOT NULL REFERENCES import_source(id),
  kind        TEXT    NOT NULL,   -- photo | video | gif | audio | file | sticker
  uri         TEXT    NOT NULL,   -- relative to import_source.export_root
  filename    TEXT,
  ts          INTEGER NOT NULL,   -- owning message's timestamp, for gallery ordering
  creation_ts INTEGER,
  size_bytes  INTEGER,
  is_missing  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (message_id, uri)
);
CREATE INDEX IF NOT EXISTS idx_media_gallery ON media(thread_id, kind, ts DESC);
CREATE INDEX IF NOT EXISTS idx_media_message ON media(message_id);

CREATE TABLE IF NOT EXISTS reaction (
  message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  actor_id   INTEGER NOT NULL REFERENCES person(id),
  emoji      TEXT    NOT NULL,
  PRIMARY KEY (message_id, actor_id, emoji)
);

-- FTS5's unicode61 tokenizer treats emoji as separators and never indexes them,
-- so emoji get their own index.  It doubles as the "most used emoji" statistic.
CREATE TABLE IF NOT EXISTS message_emoji (
  message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  thread_id  INTEGER NOT NULL,
  emoji      TEXT    NOT NULL,
  n          INTEGER NOT NULL,
  PRIMARY KEY (message_id, emoji)
);
CREATE INDEX IF NOT EXISTS idx_emoji ON message_emoji(emoji, thread_id);

CREATE TABLE IF NOT EXISTS bookmark (
  message_id INTEGER PRIMARY KEY REFERENCES message(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  note       TEXT
);

-- Precomputed analytics so the dashboard stays instant at millions of rows.
CREATE TABLE IF NOT EXISTS thread_month_stats (
  thread_id     INTEGER NOT NULL,
  ym            TEXT    NOT NULL,   -- 'YYYY-MM' in local export time (UTC)
  sender_id     INTEGER NOT NULL,
  message_count INTEGER NOT NULL,
  word_count    INTEGER NOT NULL,
  media_count   INTEGER NOT NULL,
  PRIMARY KEY (thread_id, ym, sender_id)
);
CREATE INDEX IF NOT EXISTS idx_tms_thread ON thread_month_stats(thread_id, ym);

CREATE TABLE IF NOT EXISTS thread_word_freq (
  thread_id INTEGER NOT NULL,
  word      TEXT    NOT NULL,
  n         INTEGER NOT NULL,
  PRIMARY KEY (thread_id, word)
);

CREATE TABLE IF NOT EXISTS thread_emoji_freq (
  thread_id INTEGER NOT NULL,
  emoji     TEXT    NOT NULL,
  n         INTEGER NOT NULL,
  PRIMARY KEY (thread_id, emoji)
);

-- External-content FTS: the text lives in `message`, never duplicated here.
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
  content,
  content = 'message',
  content_rowid = 'id',
  tokenize = "unicode61 remove_diacritics 2"
);
