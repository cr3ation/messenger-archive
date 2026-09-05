import { useEffect, useRef, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { api } from '../api'
import { formatDateTime, formatNumber, splitSnippet } from '../lib/format'
import type { SearchResult, SourceKind, Thread } from '../types'

interface Props {
  thread: Thread | null
  sources: SourceKind[]
  onOpenResult: (result: SearchResult, terms: string[]) => void
  onClose: () => void
}

type Scope = 'thread' | 'all'

export function SearchPanel({ thread, sources, onOpenResult, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<Scope>(thread ? 'thread' : 'all')
  const [order, setOrder] = useState<'relevance' | 'newest' | 'oldest'>('relevance')
  const [results, setResults] = useState<SearchResult[]>([])
  const [total, setTotal] = useState(0)
  const [terms, setTerms] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => inputRef.current?.focus(), [])
  useEffect(() => {
    if (!thread && scope === 'thread') setScope('all')
  }, [thread, scope])

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setResults([])
      setTotal(0)
      setTerms([])
      setError(null)
      return
    }

    let cancelled = false
    setBusy(true)
    const timer = setTimeout(async () => {
      try {
        const [hits, termResponse] = await Promise.all([
          api.search({
            q: trimmed,
            thread_id: scope === 'thread' && thread ? thread.id : undefined,
            sources: sources.join(','),
            order,
            limit: 60,
          }),
          api.searchTerms(trimmed),
        ])
        if (cancelled) return
        setResults(hits.results)
        setTotal(hits.total)
        setTerms(termResponse.terms)
        setError(null)
      } catch (problem) {
        if (!cancelled) setError((problem as Error).message)
      } finally {
        if (!cancelled) setBusy(false)
      }
    }, 220)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, scope, order, thread, sources])

  return (
    <div className="flex h-full w-96 shrink-0 flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <header className="flex items-center gap-2 border-b border-zinc-200 p-3 dark:border-zinc-800">
        <div className="relative flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search words, phrases or emoji…"
            className="input pl-9"
            type="search"
          />
        </div>
        <button type="button" onClick={onClose} className="btn-ghost px-2" aria-label="Close search">
          <X size={16} />
        </button>
      </header>

      <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 text-xs dark:border-zinc-800">
        <div className="flex rounded-lg bg-zinc-100 p-0.5 dark:bg-zinc-800">
          <button
            type="button"
            disabled={!thread}
            onClick={() => setScope('thread')}
            className={`rounded-md px-2 py-1 transition-colors disabled:opacity-40 ${
              scope === 'thread' ? 'bg-white shadow-sm dark:bg-zinc-700' : ''
            }`}
          >
            This chat
          </button>
          <button
            type="button"
            onClick={() => setScope('all')}
            className={`rounded-md px-2 py-1 transition-colors ${
              scope === 'all' ? 'bg-white shadow-sm dark:bg-zinc-700' : ''
            }`}
          >
            All chats
          </button>
        </div>

        <select
          value={order}
          onChange={(event) => setOrder(event.target.value as typeof order)}
          className="ml-auto rounded-lg border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-700"
        >
          <option value="relevance">Most relevant</option>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {error && <p className="p-4 text-sm text-red-500">{error}</p>}

        {!error && query.trim() && (
          <p className="flex items-center gap-2 px-4 py-2 text-xs text-zinc-500">
            {busy && <Loader2 size={12} className="animate-spin" />}
            {formatNumber(total)} results
            {total > results.length && ` · visar ${results.length}`}
          </p>
        )}

        <ul>
          {results.map((result) => (
            <li key={result.id}>
              <button
                type="button"
                onClick={() => onOpenResult(result, terms)}
                className="w-full border-b border-zinc-100 px-4 py-3 text-left hover:bg-zinc-50 dark:border-zinc-800/70 dark:hover:bg-zinc-800/50"
              >
                <div className="flex items-baseline gap-2">
                  <span className="truncate text-xs font-medium text-indigo-600 dark:text-indigo-400">
                    {scope === 'all' ? result.thread_title : result.sender}
                  </span>
                  <span className="ml-auto shrink-0 text-[0.6875rem] text-zinc-400">
                    {formatDateTime(result.ts)}
                  </span>
                </div>
                {scope === 'all' && (
                  <span className="text-[0.6875rem] text-zinc-500">{result.sender}</span>
                )}
                <p className="mt-1 line-clamp-3 text-sm text-zinc-700 dark:text-zinc-300">
                  {splitSnippet(result.snippet || result.content || '').map((part, index) =>
                    part.hit ? (
                      <mark key={index}>{part.text}</mark>
                    ) : (
                      <span key={index}>{part.text}</span>
                    ),
                  )}
                </p>
              </button>
            </li>
          ))}
        </ul>

        {!busy && query.trim() && !results.length && !error && (
          <p className="p-6 text-center text-sm text-zinc-500">No matches.</p>
        )}

        {!query.trim() && (
          <div className="p-6 text-center text-sm text-zinc-500">
            <p>Search {scope === 'thread' ? 'this conversation' : 'the whole archive'}.</p>
            <p className="mt-2 text-xs">
              Quote a phrase: <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">"god jul"</code>
              <br />
              Emoji work too: <span className="text-base">❤️ 😂 👍</span>
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
