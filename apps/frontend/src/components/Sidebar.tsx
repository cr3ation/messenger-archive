import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  Image as ImageIcon,
  MessageSquare,
  Search,
  ShieldAlert,
  Star,
  User,
  Users,
} from 'lucide-react'
import { formatNumber, formatRelative } from '../lib/format'
import type { SourceKind, Thread } from '../types'
import { Avatar } from './Avatar'

interface Props {
  threads: Thread[]
  loading: boolean
  selectedId: number | null
  filter: string
  sources: SourceKind[]
  onFilterChange: (value: string) => void
  onSourcesChange: (sources: SourceKind[]) => void
  onSelect: (thread: Thread) => void
}

const SOURCE_TOGGLES: { key: SourceKind; label: string; icon: typeof Archive; hint: string }[] = [
  { key: 'archived_threads', label: 'Archived', icon: Archive, hint: 'Archived conversations' },
  { key: 'message_requests', label: 'Requests', icon: MessageSquare, hint: 'Message requests' },
  { key: 'filtered_threads', label: 'Spam', icon: ShieldAlert, hint: 'Filtered conversations (spam)' },
]

export function Sidebar({
  threads,
  loading,
  selectedId,
  filter,
  sources,
  onFilterChange,
  onSourcesChange,
  onSelect,
}: Props) {
  const [draft, setDraft] = useState(filter)

  // Debounce so typing in a 1 000-conversation list doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => onFilterChange(draft), 180)
    return () => clearTimeout(timer)
  }, [draft, onFilterChange])

  const toggleSource = (key: SourceKind) => {
    onSourcesChange(sources.includes(key) ? sources.filter((s) => s !== key) : [...sources, key])
  }

  const total = useMemo(
    () => threads.reduce((sum, thread) => sum + thread.message_count, 0),
    [threads],
  )

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-200 p-3 dark:border-zinc-800">
        <div className="relative">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
          />
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Search people or groups…"
            className="input pl-9"
            type="search"
          />
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {SOURCE_TOGGLES.map(({ key, label, icon: Icon, hint }) => {
            const active = sources.includes(key)
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleSource(key)}
                title={hint}
                aria-pressed={active}
                className={`chip border transition-colors ${
                  active
                    ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-600 dark:text-indigo-300'
                    : 'border-zinc-200 text-zinc-500 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-500 dark:hover:bg-zinc-800'
                }`}
              >
                <Icon size={12} />
                {label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && threads.length === 0 ? (
          <ul className="space-y-1 p-2">
            {Array.from({ length: 10 }).map((_, index) => (
              <li key={index} className="flex gap-3 rounded-lg p-2">
                <div className="h-10 w-10 shrink-0 animate-pulse rounded-full bg-zinc-200 dark:bg-zinc-800" />
                <div className="flex-1 space-y-2 py-1">
                  <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="h-2.5 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                </div>
              </li>
            ))}
          </ul>
        ) : threads.length === 0 ? (
          <p className="p-6 text-center text-sm text-zinc-500">No conversations match.</p>
        ) : (
          <ul className="p-2">
            {threads.map((thread) => {
              const active = thread.id === selectedId
              const other = thread.participants.find((p) => !p.is_owner)
              const preview = thread.last_content
                ? thread.last_content
                : thread.last_has_media
                  ? 'Attachment'
                  : ''

              return (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(thread)}
                    className={`flex w-full gap-3 rounded-lg p-2 text-left transition-colors ${
                      active
                        ? 'bg-indigo-500/15'
                        : 'hover:bg-zinc-100 dark:hover:bg-zinc-800/70'
                    }`}
                  >
                    <Avatar
                      name={thread.is_group ? thread.title : (other?.name ?? thread.title)}
                      hue={other?.hue ?? 220}
                      group={thread.is_group}
                      size={40}
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span
                          className={`truncate text-sm ${
                            active
                              ? 'font-semibold text-indigo-700 dark:text-indigo-200'
                              : 'font-medium'
                          }`}
                        >
                          {thread.title}
                        </span>
                        <span className="ml-auto shrink-0 text-[0.6875rem] tabular-nums text-zinc-400">
                          {formatRelative(thread.last_ts)}
                        </span>
                      </div>

                      <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                        {thread.last_sender && preview ? `${thread.last_sender}: ` : ''}
                        {preview || '—'}
                      </p>

                      <div className="mt-1 flex items-center gap-2 text-[0.6875rem] text-zinc-400 dark:text-zinc-500">
                        <span className="inline-flex items-center gap-1">
                          {thread.is_group ? <Users size={11} /> : <User size={11} />}
                          {thread.is_group ? `${thread.participant_count} personer` : 'Direct'}
                        </span>
                        <span className="tabular-nums">{formatNumber(thread.message_count)}</span>
                        {thread.media_count > 0 && (
                          <span className="inline-flex items-center gap-0.5 tabular-nums">
                            <ImageIcon size={11} />
                            {formatNumber(thread.media_count)}
                          </span>
                        )}
                        {thread.source === 'filtered_threads' && (
                          <ShieldAlert size={11} className="text-amber-500" aria-label="Spam" />
                        )}
                        {thread.source === 'archived_threads' && (
                          <Archive size={11} aria-label="Archived" />
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-zinc-200 px-3 py-2 text-[0.6875rem] text-zinc-500 dark:border-zinc-800">
        <Star size={11} />
        {formatNumber(threads.length)} conversations · {formatNumber(total)} messages
      </div>
    </aside>
  )
}
