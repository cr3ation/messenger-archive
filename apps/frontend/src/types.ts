export type SourceKind =
  | 'inbox'
  | 'e2ee_cutover'
  | 'secure_storage'
  | 'archived_threads'
  | 'message_requests'
  | 'filtered_threads'

export interface Participant {
  name: string
  hue: number
  is_owner: boolean
}

export interface Thread {
  id: number
  thread_key: string
  title: string
  source: SourceKind
  is_group: boolean
  participant_count: number
  image_uri: string | null
  first_ts: number | null
  last_ts: number | null
  message_count: number
  media_count: number
  last_content: string | null
  last_has_media: number | null
  last_sender: string | null
  participants: Participant[]
  others: string[]
}

export interface MediaItem {
  id: number
  kind: 'photo' | 'video' | 'gif' | 'audio' | 'file' | 'sticker' | 'unavailable'
  filename: string | null
  size_bytes: number | null
  is_missing: boolean
}

export interface Reaction {
  emoji: string
  actor: string
}

export interface Message {
  id: number
  thread_id: number
  seq: number
  ts: number
  content: string | null
  share_link: string | null
  share_text: string | null
  sticker_uri: string | null
  call_duration: number | null
  is_unsent: boolean
  sender: string
  sender_hue: number
  is_own: boolean
  media: MediaItem[]
  reactions: Reaction[]
  bookmarked: boolean
}

export interface SearchResult {
  id: number
  thread_id: number
  seq: number
  ts: number
  content: string | null
  sender: string
  thread_title: string
  is_group: boolean
  snippet: string
}

export interface GalleryItem {
  id: number
  message_id: number
  kind: MediaItem['kind']
  filename: string | null
  ts: number
  size_bytes: number | null
  seq: number
  sender: string
}

/** A month with the absolute position to jump to — `seq` in a chat, `offset` in the gallery. */
export interface MonthBucket {
  ym: string
  n: number
  seq: number
  offset: number
}

export interface ArchiveState {
  threads: number
  messages: number
  media: number
  bookmarks: number
  owner: string | null
  sources: { source: SourceKind; n: number }[]
  archives: {
    archive_name: string
    imported_at: number
    thread_count: number
    message_count: number
  }[]
  first_ts: number | null
  last_ts: number | null
  has_data: boolean
}

export interface ImportProgress {
  state: 'idle' | 'unpacking' | 'running' | 'deriving' | 'done' | 'error'
  archive: string
  threads_total: number
  threads_done: number
  messages: number
  media: number
  owner: string | null
  error: string | null
  elapsed: number
  log: string[]
}

export interface ThreadStats {
  thread: {
    id: number
    title: string
    is_group: boolean
    message_count: number
    media_count: number
    first_ts: number | null
    last_ts: number | null
    active_days: number
  }
  senders: {
    sender: string
    hue: number
    is_owner: boolean
    messages: number
    words: number
    media: number
    share: number
  }[]
  months: { ym: string; n: number }[]
  years: { year: string; n: number }[]
  hours: { hour: number; n: number }[]
  weekdays: { weekday: number; n: number }[]
  busiest_day: { day: string; n: number } | null
  emoji: { emoji: string; n: number }[]
  words: { word: string; n: number }[]
  media_kinds: { kind: string; n: number }[]
}

export interface Bookmark {
  message_id: number
  created_at: number
  note: string | null
  thread_id: number
  seq: number
  ts: number
  content: string | null
  has_media: number
  sender: string
  thread_title: string
  is_group: boolean
}

/** Where the chat view should scroll to, and what to flash when it lands. */
export interface JumpTarget {
  seq: number
  messageId?: number
  terms?: string[]
  nonce: number
}
