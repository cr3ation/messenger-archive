import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarClock, ChevronsDown, ChevronsUp } from 'lucide-react'
import { api } from '../api'
import { MONTH_NAMES, formatNumber } from '../lib/format'
import type { MonthBucket, Thread } from '../types'

interface Props {
  thread: Thread
  onJump: (seq: number) => void
}

/**
 * Year/month picker for a conversation.
 *
 * Every month bucket carries the `seq` of its first message, so picking one is a
 * direct scroll to an absolute row — no scanning, no date maths at click time.
 */
export function TimeTravel({ thread, onJump }: Props) {
  const [open, setOpen] = useState(false)
  const [months, setMonths] = useState<MonthBucket[]>([])
  const [activeYear, setActiveYear] = useState<string | null>(null)
  const popover = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setOpen(false)
    setMonths([])
    setActiveYear(null)
  }, [thread.id])

  useEffect(() => {
    if (!open || months.length) return
    api
      .timeline(thread.id)
      .then((response) => {
        setMonths(response.months)
        const years = [...new Set(response.months.map((m) => m.ym.slice(0, 4)))]
        setActiveYear(years[years.length - 1] ?? null)
      })
      .catch(() => setMonths([]))
  }, [open, thread.id, months.length])

  useEffect(() => {
    if (!open) return
    const onClickOutside = (event: MouseEvent) => {
      if (popover.current && !popover.current.contains(event.target as Node)) setOpen(false)
    }
    const onEscape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  const byYear = useMemo(() => {
    const grouped = new Map<string, MonthBucket[]>()
    for (const month of months) {
      const year = month.ym.slice(0, 4)
      const list = grouped.get(year) ?? []
      list.push(month)
      grouped.set(year, list)
    }
    return grouped
  }, [months])

  const years = useMemo(() => [...byYear.keys()], [byYear])
  const peak = useMemo(
    () => Math.max(1, ...months.map((month) => month.n)),
    [months],
  )

  const jump = (seq: number) => {
    onJump(seq)
    setOpen(false)
  }

  return (
    <div className="relative flex items-center gap-1" ref={popover}>
      <button
        type="button"
        onClick={() => onJump(0)}
        title="Jump to the start of the conversation"
        aria-label="Jump to the start of the conversation"
        className="btn-ghost px-2"
      >
        <ChevronsUp size={16} />
      </button>

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="btn-ghost px-2"
        title="Jump to a month"
        aria-expanded={open}
      >
        <CalendarClock size={16} />
      </button>

      <button
        type="button"
        onClick={() => onJump(Math.max(0, thread.message_count - 1))}
        title="Jump to the latest message"
        aria-label="Jump to the latest message"
        className="btn-ghost px-2"
      >
        <ChevronsDown size={16} />
      </button>

      {open && (
        <div className="panel absolute right-0 top-11 z-30 w-80 animate-slide-up rounded-xl border p-3 shadow-xl">
          {!months.length ? (
            <p className="py-6 text-center text-sm text-zinc-500">Loading timeline…</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1 border-b border-zinc-200 pb-2 dark:border-zinc-800">
                {years.map((year) => (
                  <button
                    key={year}
                    type="button"
                    onClick={() => setActiveYear(year)}
                    className={`rounded-md px-2 py-1 text-xs tabular-nums transition-colors ${
                      year === activeYear
                        ? 'bg-indigo-600 text-white'
                        : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
                    }`}
                  >
                    {year}
                  </button>
                ))}
              </div>

              <div className="mt-2 grid grid-cols-3 gap-1">
                {MONTH_NAMES.map((label, index) => {
                  const key = `${activeYear}-${String(index + 1).padStart(2, '0')}`
                  const bucket = months.find((month) => month.ym === key)
                  const intensity = bucket ? Math.max(0.12, bucket.n / peak) : 0

                  return (
                    <button
                      key={label}
                      type="button"
                      disabled={!bucket}
                      onClick={() => bucket && jump(bucket.seq)}
                      title={bucket ? `${formatNumber(bucket.n)} messages` : 'No messages'}
                      className="relative overflow-hidden rounded-md px-2 py-2 text-xs capitalize transition-colors disabled:cursor-not-allowed disabled:opacity-30 enabled:hover:ring-2 enabled:hover:ring-indigo-500/50"
                    >
                      <span
                        className="absolute inset-0 bg-indigo-500"
                        style={{ opacity: intensity * 0.55 }}
                        aria-hidden
                      />
                      <span className="relative">{label}</span>
                      {bucket && (
                        <span className="relative block text-[0.625rem] tabular-nums opacity-70">
                          {formatNumber(bucket.n)}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
