import type {
  ArchiveState,
  Bookmark,
  GalleryItem,
  ImportProgress,
  Message,
  MonthBucket,
  SearchResult,
  SourceKind,
  Thread,
  ThreadStats,
} from './types'

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = (await response.json()).detail ?? detail
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

const query = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}

export const api = {
  state: () => json<ArchiveState>('/api/state'),

  threads: (params: { q?: string; sources?: string; limit?: number }) =>
    json<{ threads: Thread[] }>(`/api/threads${query(params)}`),

  thread: (id: number) => json<Thread>(`/api/threads/${id}`),

  messages: (id: number, fromSeq: number, limit: number) =>
    json<{ messages: Message[]; from_seq: number }>(
      `/api/threads/${id}/messages${query({ from_seq: fromSeq, limit })}`,
    ),

  locate: (id: number, target: { ts?: number; ym?: string; message_id?: number }) =>
    json<{ seq: number; ts: number }>(`/api/threads/${id}/locate${query(target)}`),

  timeline: (id: number) => json<{ months: MonthBucket[] }>(`/api/threads/${id}/timeline`),

  search: (params: {
    q: string
    thread_id?: number
    sources?: string
    order?: string
    limit?: number
    offset?: number
  }) => json<{ results: SearchResult[]; total: number; mode: string }>(`/api/search${query(params)}`),

  searchTerms: (q: string) => json<{ terms: string[] }>(`/api/search/terms${query({ q })}`),

  media: (id: number, kinds: string, limit: number, offset: number) =>
    json<{
      items: GalleryItem[]
      counts: Record<string, number>
      total: number
      offset: number
    }>(`/api/threads/${id}/media${query({ kinds, limit, offset })}`),

  /** Position of a media item in the gallery, by id or by moment in time. */
  locateMedia: (id: number, target: { media_id?: number; ts?: number; kinds?: string }) =>
    json<{ offset: number; media_id: number; kind: string; ts: number }>(
      `/api/threads/${id}/media/locate${query(target)}`,
    ),

  mediaTimeline: (id: number, kinds: string) =>
    json<{ months: MonthBucket[] }>(`/api/threads/${id}/media/timeline${query({ kinds })}`),

  stats: (id: number) => json<ThreadStats>(`/api/threads/${id}/stats`),

  bookmarks: (threadId?: number) =>
    json<{ bookmarks: Bookmark[]; total: number }>(`/api/bookmarks${query({ thread_id: threadId })}`),

  addBookmark: (messageId: number, note?: string) =>
    json<{ bookmarked: boolean }>('/api/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId, note }),
    }),

  removeBookmark: (messageId: number) =>
    json<{ bookmarked: boolean }>(`/api/bookmarks/${messageId}`, { method: 'DELETE' }),

  uploads: () => json<{ uploads: { name: string; size_bytes: number }[] }>('/api/admin/uploads'),

  deleteUpload: (name: string) =>
    json<{ deleted: boolean }>(`/api/admin/uploads/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  disk: () => json<{ free_bytes: number; total_bytes: number }>('/api/admin/disk'),

  /** `reset` wipes the database *and* the unpacked originals in ./exports/. */
  startImport: (uploads: string[], reset = false) =>
    json<ImportProgress>('/api/admin/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uploads, reset }),
    }),

  importStatus: () => json<ImportProgress>('/api/admin/import/status'),
}

export const mediaUrl = (id: number) => `/media/${id}`
export const downloadUrl = (id: number) => `/media/${id}?download=true`
export const thumbUrl = (id: number, width = 320) => `/thumb/${id}?w=${width}`

/**
 * Upload one archive, reporting real progress.
 *
 * Uses XMLHttpRequest rather than fetch because only XHR exposes upload
 * progress events, and a multi-gigabyte archive without a progress bar looks
 * indistinguishable from a hung app.
 */
export function uploadArchive(
  file: File,
  onProgress: (loaded: number, total: number) => void,
): { promise: Promise<{ name: string; size_bytes: number }>; abort: () => void } {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<{ name: string; size_bytes: number }>((resolve, reject) => {
    xhr.open('POST', `/api/admin/upload?filename=${encodeURIComponent(file.name)}`)
    xhr.setRequestHeader('Content-Type', 'application/zip')

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total)
    })
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        let detail = `Upload failed (${xhr.status})`
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail
        } catch {
          /* body was not JSON */
        }
        reject(new Error(detail))
      }
    })
    xhr.addEventListener('error', () => reject(new Error('Network error during upload')))
    xhr.addEventListener('abort', () => reject(new Error('Upload cancelled')))
    xhr.send(file)
  })

  return { promise, abort: () => xhr.abort() }
}

export const DEFAULT_SOURCES: SourceKind[] = ['inbox', 'e2ee_cutover', 'archived_threads']
