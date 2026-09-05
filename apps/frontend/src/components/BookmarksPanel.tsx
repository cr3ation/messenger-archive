import { useEffect, useState } from 'react'
import { Star, X } from 'lucide-react'
import { api } from '../api'
import { formatDateTime, formatNumber } from '../lib/format'
import type { Bookmark } from '../types'

interface Props {
  refreshToken: number
  onOpen: (bookmark: Bookmark) => void
  onClose: () => void
}

export function BookmarksPanel({ refreshToken, onOpen, onClose }: Props) {
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api
      .bookmarks()
      .then((response) => setBookmarks(response.bookmarks))
      .finally(() => setLoading(false))
  }, [refreshToken])

  const remove = async (messageId: number) => {
    setBookmarks((current) => current.filter((entry) => entry.message_id !== messageId))
    await api.removeBookmark(messageId)
  }

  return (
    <div className="flex h-full w-96 shrink-0 flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <header className="flex items-center justify-between border-b border-zinc-200 p-3 dark:border-zinc-800">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Star size={15} className="fill-amber-400 text-amber-400" />
          Saved memories
          {bookmarks.length > 0 && (
            <span className="text-xs font-normal tabular-nums text-zinc-500">
              {formatNumber(bookmarks.length)}
            </span>
          )}
        </h2>
        <button type="button" onClick={onClose} className="btn-ghost px-2" aria-label="Close">
          <X size={16} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="p-6 text-center text-sm text-zinc-500">Loading…</p>}

        {!loading && bookmarks.length === 0 && (
          <div className="p-6 text-center text-sm text-zinc-500">
            <Star size={22} className="mx-auto mb-2 opacity-30" />
            <p>No saved memories yet.</p>
            <p className="mt-1 text-xs">
              Hover a message and click the star.
            </p>
          </div>
        )}

        <ul>
          {bookmarks.map((bookmark) => (
            <li
              key={bookmark.message_id}
              className="group border-b border-zinc-100 dark:border-zinc-800/70"
            >
              <div className="flex items-start">
                <button
                  type="button"
                  onClick={() => onOpen(bookmark)}
                  className="min-w-0 flex-1 px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-xs font-medium text-indigo-600 dark:text-indigo-400">
                      {bookmark.thread_title}
                    </span>
                    <span className="ml-auto shrink-0 text-[0.6875rem] text-zinc-400">
                      {formatDateTime(bookmark.ts)}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-3 text-sm text-zinc-700 dark:text-zinc-300">
                    <span className="text-zinc-500">{bookmark.sender}: </span>
                    {bookmark.content || (bookmark.has_media ? 'Attachment' : '—')}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => remove(bookmark.message_id)}
                  className="mt-3 mr-2 rounded p-1 text-zinc-400 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                  aria-label="Remove bookmark"
                  title="Remove bookmark"
                >
                  <X size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
