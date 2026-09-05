import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'
import { WEEKDAY_NAMES, formatNumber } from '../lib/format'
import type { Thread, ThreadStats } from '../types'
import { Avatar } from './Avatar'

interface Props {
  thread: Thread
  onClose: () => void
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[0.6875rem] text-zinc-400">{hint}</p>}
    </div>
  )
}

/**
 * Bar series. Deliberately plain SVG-free markup: at this size a div per bar
 * outperforms a chart library and stays readable in both themes.
 */
function Bars({
  data,
  labelFor,
  titleFor,
}: {
  data: { key: string; n: number }[]
  labelFor: (key: string, index: number) => string
  titleFor: (entry: { key: string; n: number }) => string
}) {
  const peak = Math.max(1, ...data.map((entry) => entry.n))
  return (
    <div className="flex h-28 items-end gap-[2px]">
      {data.map((entry, index) => (
        <div key={entry.key} className="group relative flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full rounded-t bg-indigo-500/70 transition-colors group-hover:bg-indigo-400"
            style={{ height: `${Math.max(2, (entry.n / peak) * 88)}px` }}
            title={titleFor(entry)}
          />
          <span className="text-[0.5625rem] text-zinc-400">{labelFor(entry.key, index)}</span>
        </div>
      ))}
    </div>
  )
}

export function StatsDialog({ thread, onClose }: Props) {
  const [stats, setStats] = useState<ThreadStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.stats(thread.id).then(setStats).catch((problem) => setError((problem as Error).message))
  }, [thread.id])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const years = useMemo(
    () => stats?.years.map((entry) => ({ key: entry.year, n: entry.n })) ?? [],
    [stats],
  )
  const hours = useMemo(() => {
    const filled = Array.from({ length: 24 }, (_, hour) => ({ key: String(hour), n: 0 }))
    for (const entry of stats?.hours ?? []) filled[entry.hour] = { key: String(entry.hour), n: entry.n }
    return filled
  }, [stats])
  const weekdays = useMemo(() => {
    const filled = Array.from({ length: 7 }, (_, day) => ({ key: String(day), n: 0 }))
    for (const entry of stats?.weekdays ?? []) filled[entry.weekday] = { key: String(entry.weekday), n: entry.n }
    // Swedish weeks start on Monday; the database counts Sunday as 0.
    return [...filled.slice(1), filled[0]]
  }, [stats])

  const span =
    stats?.thread.first_ts && stats.thread.last_ts
      ? `${new Date(stats.thread.first_ts).getFullYear()}–${new Date(stats.thread.last_ts).getFullYear()}`
      : ''

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal
    >
      <div
        className="panel max-h-[90vh] w-full max-w-3xl animate-slide-up overflow-y-auto rounded-2xl border shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sticky top-0 flex items-center gap-3 border-b border-zinc-200 bg-white/90 p-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{thread.title}</h2>
            <p className="text-xs text-zinc-500">Chat statistics {span}</p>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost ml-auto px-2" aria-label="Close">
            <X size={16} />
          </button>
        </header>

        {error && <p className="p-6 text-sm text-red-500">{error}</p>}
        {!stats && !error && <p className="p-10 text-center text-sm text-zinc-500">Crunching…</p>}

        {stats && (
          <div className="space-y-6 p-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile label="Messages" value={formatNumber(stats.thread.message_count)} />
              <Tile label="Media" value={formatNumber(stats.thread.media_count)} />
              <Tile label="Active days" value={formatNumber(stats.thread.active_days)} />
              <Tile
                label="Busiest day"
                value={stats.busiest_day ? formatNumber(stats.busiest_day.n) : '—'}
                hint={stats.busiest_day?.day}
              />
            </div>

            <section>
              <h3 className="mb-2 text-sm font-medium">Who talks the most</h3>
              <div className="space-y-2">
                {stats.senders.slice(0, 12).map((sender) => (
                  <div key={sender.sender} className="flex items-center gap-3">
                    <Avatar name={sender.sender} hue={sender.hue} size={26} />
                    <span className="w-40 shrink-0 truncate text-sm">{sender.sender}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                      <div
                        className={`h-full rounded-full ${
                          sender.is_owner ? 'bg-indigo-500' : 'bg-teal-500'
                        }`}
                        style={{ width: `${sender.share}%` }}
                      />
                    </div>
                    <span className="w-24 shrink-0 text-right text-xs tabular-nums text-zinc-500">
                      {formatNumber(sender.messages)} · {sender.share}%
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-sm font-medium">Activity by year</h3>
              <Bars
                data={years}
                labelFor={(key) => `'${key.slice(2)}`}
                titleFor={(entry) => `${entry.key}: ${formatNumber(entry.n)} messages`}
              />
            </section>

            <div className="grid gap-6 sm:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-medium">Time of day</h3>
                <Bars
                  data={hours}
                  labelFor={(key, index) => (index % 3 === 0 ? key : '')}
                  titleFor={(entry) => `kl ${entry.key}: ${formatNumber(entry.n)}`}
                />
              </section>

              <section>
                <h3 className="mb-2 text-sm font-medium">Day of week</h3>
                <Bars
                  data={weekdays}
                  labelFor={(key) => WEEKDAY_NAMES[Number(key)]}
                  titleFor={(entry) => `${WEEKDAY_NAMES[Number(entry.key)]}: ${formatNumber(entry.n)}`}
                />
              </section>
            </div>

            <div className="grid gap-6 sm:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-medium">Most used emoji</h3>
                {stats.emoji.length ? (
                  <ul className="flex flex-wrap gap-2">
                    {stats.emoji.map((entry) => (
                      <li
                        key={entry.emoji}
                        className="flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2 py-1 dark:border-zinc-800"
                      >
                        <span className="text-lg leading-none">{entry.emoji}</span>
                        <span className="text-xs tabular-nums text-zinc-500">
                          {formatNumber(entry.n)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-zinc-500">No emoji here.</p>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-sm font-medium">Most common words</h3>
                {stats.words.length ? (
                  <ul className="flex flex-wrap gap-1.5">
                    {stats.words.map((entry) => (
                      <li
                        key={entry.word}
                        className="chip bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                        title={`${formatNumber(entry.n)} times`}
                      >
                        {entry.word}
                        <span className="tabular-nums opacity-50">{formatNumber(entry.n)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-zinc-500">Not enough text to count.</p>
                )}
              </section>
            </div>

            <p className="text-xs text-zinc-400">
              {stats.months.length} months with activity, from{' '}
              {stats.months[0]?.ym.replace('-', ' ')} to{' '}
              {stats.months[stats.months.length - 1]?.ym.replace('-', ' ')}. Times are shown in
              UTC, the way Facebook stores them.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
