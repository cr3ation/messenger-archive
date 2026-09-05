import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown } from 'lucide-react'
import { api } from '../api'
import { formatDay, isSameDay } from '../lib/format'
import { useThreadWindow } from '../hooks/useThreadWindow'
import type { JumpTarget, Message, Thread } from '../types'
import { MessageBubble } from './MessageBubble'

interface Props {
  thread: Thread
  jump: JumpTarget | null
  terms: string[]
  onOpenMedia: (mediaId: number) => void
  onBookmarkChange: () => void
  /** Timestamp of the topmost visible message, so the gallery can follow along. */
  onAnchorChange?: (ts: number) => void
}

const ESTIMATED_ROW = 72

export function ChatView({
  thread,
  jump,
  terms,
  onOpenMedia,
  onBookmarkChange,
  onAnchorChange,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const count = thread.message_count
  const { get, has, patch, ensureRange, version } = useThreadWindow(thread.id, count)
  const [atBottom, setAtBottom] = useState(true)

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW,
    overscan: 10,
    getItemKey: (index) => index,
  })

  const items = virtualizer.getVirtualItems()

  // Fetch exactly the pages the viewport is about to paint.
  useEffect(() => {
    if (!items.length) return
    ensureRange(items[0].index, items[items.length - 1].index)
  }, [items, ensureRange])

  // A conversation opens at its most recent message, the way a chat app does.
  const openedRef = useRef<number | null>(null)
  useLayoutEffect(() => {
    if (openedRef.current === thread.id || count === 0) return
    openedRef.current = thread.id
    virtualizer.scrollToIndex(count - 1, { align: 'end' })
    setAtBottom(true)
  }, [thread.id, count, virtualizer])

  /*
   * Jumping is a two-step affair. Rows are estimated until they have been
   * measured, so the first scroll lands approximately; once the target's page
   * has loaded and its real height is known, we scroll again to land exactly.
   */
  const settleRef = useRef<{ seq: number; nonce: number; tries: number } | null>(null)

  useLayoutEffect(() => {
    if (!jump) return
    settleRef.current = { seq: jump.seq, nonce: jump.nonce, tries: 0 }
    virtualizer.scrollToIndex(jump.seq, { align: 'center' })
    ensureRange(Math.max(0, jump.seq - 40), jump.seq + 40)
  }, [jump, virtualizer, ensureRange])

  useLayoutEffect(() => {
    const settle = settleRef.current
    if (!settle) return
    if (!has(settle.seq)) return
    if (settle.tries >= 3) {
      settleRef.current = null
      return
    }
    settle.tries += 1
    virtualizer.scrollToIndex(settle.seq, { align: 'center' })
  }, [version, virtualizer, has])

  const handleScroll = useCallback(() => {
    const element = scrollRef.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    setAtBottom(distance < 120)
  }, [])

  /*
   * Report where the reader is, in time. The media gallery uses it to show what
   * was shared around this point in the conversation. Throttled to the topmost
   * rendered row rather than fired per scrolled pixel.
   */
  const lastAnchor = useRef<number>(0)
  useEffect(() => {
    if (!onAnchorChange || !items.length) return
    const top = get(items[0].index)
    if (!top || top.ts === lastAnchor.current) return
    const timer = setTimeout(() => {
      lastAnchor.current = top.ts
      onAnchorChange(top.ts)
    }, 200)
    return () => clearTimeout(timer)
  }, [items, get, version, onAnchorChange])

  const toggleBookmark = useCallback(
    async (message: Message) => {
      const next = !message.bookmarked
      patch(message.seq, { bookmarked: next })
      try {
        if (next) await api.addBookmark(message.id)
        else await api.removeBookmark(message.id)
        onBookmarkChange()
      } catch {
        patch(message.seq, { bookmarked: !next }) // put the star back
      }
    },
    [patch, onBookmarkChange],
  )

  const highlightId = jump?.messageId
  const isGroup = thread.is_group
  const emptyThread = count === 0

  const rows = useMemo(
    () =>
      items.map((item) => {
        const message = get(item.index)
        const previous = item.index > 0 ? get(item.index - 1) : undefined
        return { item, message, previous }
      }),
    [items, get, version],
  )

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden py-4"
      >
        {emptyThread ? (
          <p className="mt-16 text-center text-sm text-zinc-500">
            This conversation has no messages.
          </p>
        ) : (
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            <div
              className="absolute left-0 top-0 w-full"
              style={{ transform: `translateY(${items[0]?.start ?? 0}px)` }}
            >
              {rows.map(({ item, message, previous }) => (
                <div key={item.key} data-index={item.index} ref={virtualizer.measureElement}>
                  {message ? (
                    <>
                      {(!previous || !isSameDay(previous.ts, message.ts)) && (
                        <div className="my-4 flex items-center gap-3 px-6">
                          <div className="h-px flex-1 bg-zinc-300 dark:bg-zinc-800" />
                          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                            {formatDay(message.ts)}
                          </span>
                          <div className="h-px flex-1 bg-zinc-300 dark:bg-zinc-800" />
                        </div>
                      )}
                      <MessageBubble
                        message={message}
                        isGroup={isGroup}
                        showSender={
                          !previous ||
                          previous.sender !== message.sender ||
                          message.ts - previous.ts > 10 * 60 * 1000
                        }
                        terms={terms}
                        highlighted={highlightId === message.id}
                        onToggleBookmark={toggleBookmark}
                        onOpenMedia={onOpenMedia}
                      />
                    </>
                  ) : (
                    <div className="px-4 py-2" style={{ height: ESTIMATED_ROW }}>
                      <div className="h-9 w-1/3 animate-pulse rounded-2xl bg-zinc-200 dark:bg-zinc-800/70" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {!atBottom && !emptyThread && (
        <button
          type="button"
          onClick={() => virtualizer.scrollToIndex(count - 1, { align: 'end' })}
          className="absolute bottom-5 right-6 flex h-10 w-10 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg transition hover:bg-indigo-500"
          title="Jump to the latest message"
          aria-label="Jump to the latest message"
        >
          <ArrowDown size={18} />
        </button>
      )}
    </div>
  )
}
