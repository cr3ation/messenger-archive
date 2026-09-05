import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { CalendarClock, FileText, Film, Link, Link2Off, Music, X } from 'lucide-react'
import { api, mediaUrl, thumbUrl } from '../api'
import { MONTH_NAMES, formatMonthKey, formatNumber, formatRelative } from '../lib/format'
import { useSparsePages } from '../hooks/useSparsePages'
import type { GalleryItem, MonthBucket, Thread } from '../types'
import { Lightbox } from './Lightbox'

interface Props {
  thread: Thread
  /** Timestamp of the message currently at the top of the chat view. */
  chatAnchorTs: number | null
  /** Set when a photo was clicked in the chat: focus it and open the lightbox. */
  focusMediaId: number | null
  onFocusHandled: () => void
  onClose: () => void
  onJumpToMessage: (item: GalleryItem) => void
}

const TABS = [
  { key: 'photo,gif', label: 'Photos', countKeys: ['photo', 'gif'] },
  { key: 'video', label: 'Video', countKeys: ['video'] },
  { key: 'file,audio', label: 'Files', countKeys: ['file', 'audio'] },
] as const

/** Every kind the gallery can show — used when we don't yet know the item's tab. */
const ALL_GALLERY_KINDS = 'photo,video,gif,file,audio'
const PAGE = 60
const COLUMNS = 3
const ROW_HEIGHT = 108
const LIST_ROW_HEIGHT = 56
/** How long the gallery stops following the chat after you scroll it yourself. */
const FOLLOW_PAUSE_MS = 4000

const tabForKind = (kind: GalleryItem['kind']) =>
  kind === 'video' ? 'video' : kind === 'file' || kind === 'audio' ? 'file,audio' : 'photo,gif'

export function MediaGallery({
  thread,
  chatAnchorTs,
  focusMediaId,
  onFocusHandled,
  onClose,
  onJumpToMessage,
}: Props) {
  const [tab, setTab] = useState<string>(TABS[0].key)
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [months, setMonths] = useState<MonthBucket[]>([])
  const [showMonths, setShowMonths] = useState(false)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const [following, setFollowing] = useState(true)
  const [visibleMonth, setVisibleMonth] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const pausedUntil = useRef(0)
  const isList = tab === 'file,audio'

  const fetchPage = useCallback(
    async (offset: number, limit: number) => {
      const response = await api.media(thread.id, tab, limit, offset)
      setCounts(response.counts)
      setTotal(response.total)
      return response.items
    },
    [thread.id, tab],
  )

  const indexOf = useCallback(
    (_item: GalleryItem, offset: number, position: number) => offset + position,
    [],
  )

  // The real total, never a placeholder: useSparsePages clamps requested ranges
  // to it, so faking a count of 1 would silently reduce every fetch to page 0.
  const pages = useSparsePages<GalleryItem>(
    `${thread.id}:${tab}`,
    total,
    PAGE,
    fetchPage,
    indexOf,
  )
  const { get, ensureRange, version } = pages

  // Counts and totals for the first paint, before any range has been requested.
  useEffect(() => {
    let cancelled = false
    api.media(thread.id, tab, 1, 0).then((response) => {
      if (cancelled) return
      setCounts(response.counts)
      setTotal(response.total)
    })
    api
      .mediaTimeline(thread.id, tab)
      .then((response) => !cancelled && setMonths(response.months))
      .catch(() => !cancelled && setMonths([]))
    return () => {
      cancelled = true
    }
  }, [thread.id, tab])

  const rowCount = isList ? total : Math.ceil(total / COLUMNS)
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (isList ? LIST_ROW_HEIGHT : ROW_HEIGHT),
    overscan: 4,
  })
  const rows = virtualizer.getVirtualItems()

  useEffect(() => {
    if (!rows.length) return
    const perRow = isList ? 1 : COLUMNS
    ensureRange(rows[0].index * perRow, (rows[rows.length - 1].index + 1) * perRow - 1)
  }, [rows, ensureRange, isList])

  // Label the month currently in view, so the position is always readable.
  useEffect(() => {
    if (!rows.length) return
    const first = get(rows[0].index * (isList ? 1 : COLUMNS))
    if (first) setVisibleMonth(new Date(first.ts).toISOString().slice(0, 7))
  }, [rows, get, version, isList])

  const scrollToOffset = useCallback(
    (offset: number) => {
      const row = isList ? offset : Math.floor(offset / COLUMNS)
      ensureRange(Math.max(0, offset - PAGE / 2), offset + PAGE / 2)
      virtualizer.scrollToIndex(row, { align: 'start' })
    },
    [virtualizer, ensureRange, isList],
  )

  /*
   * Follow the chat: whatever message is at the top of the conversation decides
   * which part of the gallery is shown. Suppressed briefly after the user
   * scrolls the gallery, otherwise the two fight over the scroll position.
   */
  useEffect(() => {
    if (!following || chatAnchorTs === null || !total) return
    if (Date.now() < pausedUntil.current) return

    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const found = await api.locateMedia(thread.id, { ts: chatAnchorTs, kinds: tab })
        if (cancelled || Date.now() < pausedUntil.current) return
        scrollToOffset(found.offset)
      } catch {
        /* nothing shared in this conversation yet */
      }
    }, 220)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [chatAnchorTs, following, total, thread.id, tab, scrollToOffset])

  /*
   * A photo clicked in the chat, resolved in two steps.
   *
   * The gallery cannot scroll to a position before it knows how many items the
   * tab holds — a range request is clamped to the known count, so acting too
   * early loads page 0 and leaves the lightbox waiting on an item that will
   * never arrive. So: first find out which tab the item lives in, then wait for
   * that tab's total before resolving the offset and opening it.
   */
  const [pendingFocus, setPendingFocus] = useState<{ mediaId: number; tab: string } | null>(null)
  const focusRef = useRef<number | null>(null)

  useEffect(() => {
    if (focusMediaId === null) {
      focusRef.current = null // so clicking the same photo again re-triggers
      return
    }
    if (focusRef.current === focusMediaId) return
    focusRef.current = focusMediaId
    let cancelled = false

    api
      .locateMedia(thread.id, { media_id: focusMediaId, kinds: ALL_GALLERY_KINDS })
      .then((found) => {
        if (cancelled) return
        const wanted = tabForKind(found.kind as GalleryItem['kind'])
        setTab(wanted)
        setPendingFocus({ mediaId: focusMediaId, tab: wanted })
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) onFocusHandled()
      })

    return () => {
      cancelled = true
    }
  }, [focusMediaId, thread.id, onFocusHandled])

  useEffect(() => {
    if (!pendingFocus || pendingFocus.tab !== tab || total <= 0) return
    let cancelled = false

    api
      .locateMedia(thread.id, { media_id: pendingFocus.mediaId, kinds: tab })
      .then((found) => {
        if (cancelled) return
        pausedUntil.current = Date.now() + FOLLOW_PAUSE_MS
        scrollToOffset(found.offset)
        setLightboxIndex(found.offset)
        setPendingFocus(null)
      })
      .catch(() => setPendingFocus(null))

    return () => {
      cancelled = true
    }
  }, [pendingFocus, tab, total, thread.id, scrollToOffset])

  const onUserScroll = useCallback(() => {
    pausedUntil.current = Date.now() + FOLLOW_PAUSE_MS
  }, [])

  const monthsByYear = useMemo(() => {
    const grouped = new Map<string, MonthBucket[]>()
    for (const month of months) {
      const year = month.ym.slice(0, 4)
      grouped.set(year, [...(grouped.get(year) ?? []), month])
    }
    return grouped
  }, [months])

  return (
    <div className="flex h-full w-96 shrink-0 flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <header className="flex items-center gap-1 border-b border-zinc-200 p-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold">Shared media</h2>

        <button
          type="button"
          onClick={() => {
            pausedUntil.current = 0
            setFollowing((value) => !value)
          }}
          title={
            following
              ? 'Following your position in the chat — click to detach the gallery'
              : 'Gallery is detached — click to follow the chat again'
          }
          className={`chip ml-auto border transition-colors ${
            following
              ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-600 dark:text-indigo-300'
              : 'border-zinc-200 text-zinc-500 dark:border-zinc-700'
          }`}
        >
          {following ? <Link size={11} /> : <Link2Off size={11} />}
          {following ? 'Following chat' : 'Detached'}
        </button>

        <button type="button" onClick={onClose} className="btn-ghost px-2" aria-label="Close">
          <X size={16} />
        </button>
      </header>

      <div className="flex items-center gap-1 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
        {TABS.map((entry) => {
          const tabTotal = entry.countKeys.reduce((sum, key) => sum + (counts[key] ?? 0), 0)
          return (
            <button
              key={entry.key}
              type="button"
              onClick={() => setTab(entry.key)}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                tab === entry.key
                  ? 'bg-indigo-500/15 font-medium text-indigo-600 dark:text-indigo-300'
                  : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {entry.label}
              {tabTotal > 0 && (
                <span className="ml-1 tabular-nums opacity-60">{formatNumber(tabTotal)}</span>
              )}
            </button>
          )
        })}

        <div className="relative ml-auto">
          <button
            type="button"
            onClick={() => setShowMonths((value) => !value)}
            className="btn-ghost gap-1 px-2 text-xs"
            title="Jump to a month"
            aria-expanded={showMonths}
          >
            <CalendarClock size={14} />
            {visibleMonth ? formatMonthKey(visibleMonth) : 'Tid'}
          </button>

          {showMonths && (
            <div
              className="panel absolute right-0 top-9 z-30 max-h-80 w-64 animate-slide-up overflow-y-auto rounded-xl border p-2 shadow-xl"
              onMouseLeave={() => setShowMonths(false)}
            >
              {!months.length ? (
                <p className="py-4 text-center text-xs text-zinc-500">No media here.</p>
              ) : (
                [...monthsByYear.entries()].reverse().map(([year, entries]) => (
                  <div key={year} className="mb-2">
                    <p className="px-1 py-0.5 text-[0.6875rem] font-semibold text-zinc-400">
                      {year}
                    </p>
                    <div className="grid grid-cols-3 gap-1">
                      {entries.map((month) => (
                        <button
                          key={month.ym}
                          type="button"
                          onClick={() => {
                            pausedUntil.current = Date.now() + FOLLOW_PAUSE_MS
                            scrollToOffset(month.offset)
                            setShowMonths(false)
                          }}
                          className="rounded-md px-1.5 py-1 text-xs capitalize hover:bg-indigo-500/15"
                          title={`${formatNumber(month.n)} files`}
                        >
                          {MONTH_NAMES[Number(month.ym.slice(5)) - 1]}
                          <span className="block text-[0.5625rem] tabular-nums opacity-60">
                            {formatNumber(month.n)}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        onWheel={onUserScroll}
        onTouchMove={onUserScroll}
        className="min-h-0 flex-1 overflow-y-auto p-2"
      >
        {total === 0 ? (
          <p className="p-6 text-center text-sm text-zinc-500">Nothing shared here yet.</p>
        ) : (
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            <div
              className="absolute left-0 top-0 w-full"
              style={{ transform: `translateY(${rows[0]?.start ?? 0}px)` }}
            >
              {rows.map((row) => {
                if (isList) {
                  const item = get(row.index)
                  return (
                    <div key={row.key} data-index={row.index} ref={virtualizer.measureElement}>
                      {item ? (
                        <button
                          type="button"
                          onClick={() => onJumpToMessage(item)}
                          className="flex w-full items-center gap-2 rounded-lg p-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        >
                          {item.kind === 'audio' ? (
                            <Music size={16} className="shrink-0 opacity-60" />
                          ) : (
                            <FileText size={16} className="shrink-0 opacity-60" />
                          )}
                          <span className="min-w-0 flex-1">
                            <span className="block truncate">{item.filename}</span>
                            <span className="block text-xs text-zinc-500">
                              {item.sender} · {formatRelative(item.ts)}
                            </span>
                          </span>
                        </button>
                      ) : (
                        <div className="m-2 h-10 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                      )}
                    </div>
                  )
                }

                return (
                  <div key={row.key} className="grid grid-cols-3 gap-1 pb-1">
                    {Array.from({ length: COLUMNS }, (_, column) => {
                      const index = row.index * COLUMNS + column
                      if (index >= total) return <div key={column} />
                      const item = get(index)
                      if (!item) {
                        return (
                          <div
                            key={column}
                            className="aspect-square animate-pulse rounded-md bg-zinc-200 dark:bg-zinc-800"
                          />
                        )
                      }
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setLightboxIndex(index)}
                          title={`${item.sender} · ${formatRelative(item.ts)}`}
                          className="group relative aspect-square overflow-hidden rounded-md bg-zinc-200 dark:bg-zinc-800"
                        >
                          {item.kind === 'video' ? (
                            <>
                              {/* preload="metadata" shows the first frame without
                                  needing ffmpeg in the image for poster frames. */}
                              <video
                                src={mediaUrl(item.id)}
                                preload="metadata"
                                muted
                                className="h-full w-full object-cover"
                              />
                              <Film
                                size={14}
                                className="absolute bottom-1 right-1 text-white drop-shadow"
                              />
                            </>
                          ) : (
                            <img
                              src={thumbUrl(item.id, 320)}
                              alt={item.filename ?? ''}
                              loading="lazy"
                              className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
                            />
                          )}
                        </button>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {lightboxIndex !== null && (
        <Lightbox
          index={lightboxIndex}
          total={total}
          getItem={get}
          onRequestRange={ensureRange}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onJumpToMessage={(item) => {
            setLightboxIndex(null)
            onJumpToMessage(item)
          }}
        />
      )}
    </div>
  )
}
