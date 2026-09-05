import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarChart3,
  Images,
  Moon,
  Plus,
  Search,
  Star,
  Sun,
  Users,
} from 'lucide-react'
import { DEFAULT_SOURCES, api } from './api'
import { formatNumber } from './lib/format'
import type {
  ArchiveState,
  Bookmark,
  GalleryItem,
  JumpTarget,
  SearchResult,
  SourceKind,
  Thread,
} from './types'
import { Avatar } from './components/Avatar'
import { BookmarksPanel } from './components/BookmarksPanel'
import { ChatView } from './components/ChatView'
import { MediaGallery } from './components/MediaGallery'
import { SearchPanel } from './components/SearchPanel'
import { SetupWizard } from './components/SetupWizard'
import { Sidebar } from './components/Sidebar'
import { StatsDialog } from './components/StatsDialog'
import { TimeTravel } from './components/TimeTravel'

type Panel = 'none' | 'search' | 'media' | 'bookmarks'

export default function App() {
  const [state, setState] = useState<ArchiveState | null>(null)
  const [threads, setThreads] = useState<Thread[]>([])
  const [loadingThreads, setLoadingThreads] = useState(true)
  const [filter, setFilter] = useState('')
  const [sources, setSources] = useState<SourceKind[]>(DEFAULT_SOURCES)
  const [selected, setSelected] = useState<Thread | null>(null)
  const [panel, setPanel] = useState<Panel>('none')
  const [showStats, setShowStats] = useState(false)
  const [showWizard, setShowWizard] = useState(false)
  const [jump, setJump] = useState<JumpTarget | null>(null)
  const [terms, setTerms] = useState<string[]>([])
  const [bookmarkToken, setBookmarkToken] = useState(0)
  const [chatAnchorTs, setChatAnchorTs] = useState<number | null>(null)
  const [focusMediaId, setFocusMediaId] = useState<number | null>(null)
  // index.html already applied the stored preference before first paint.
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const refreshState = useCallback(async () => {
    const next = await api.state()
    setState(next)
    return next
  }, [])

  useEffect(() => {
    refreshState().catch(() => setState(null))
  }, [refreshState])

  // Conversation list, refetched when the filter or the source toggles change.
  useEffect(() => {
    if (!state?.has_data) return
    let cancelled = false
    setLoadingThreads(true)
    api
      .threads({ q: filter, sources: sources.join(','), limit: 800 })
      .then((response) => {
        if (cancelled) return
        setThreads(response.threads)
        setSelected((current) => {
          if (current) return current
          return response.threads[0] ?? null
        })
      })
      .finally(() => !cancelled && setLoadingThreads(false))
    return () => {
      cancelled = true
    }
  }, [filter, sources, state?.has_data])

  const toggleTheme = () => {
    const next = !dark
    setDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('theme', next ? 'dark' : 'light')
  }

  const openThread = useCallback((thread: Thread) => {
    setSelected(thread)
    setJump(null)
    setTerms([])
  }, [])

  /** Open a search hit: switch conversation if needed, then scroll to it. */
  const openResult = useCallback(
    async (result: SearchResult, hitTerms: string[]) => {
      let thread = threads.find((entry) => entry.id === result.thread_id) ?? null
      if (!thread) thread = await api.thread(result.thread_id)
      setSelected(thread)
      setTerms(hitTerms)
      setJump({ seq: result.seq, messageId: result.id, nonce: Date.now() })
    },
    [threads],
  )

  const openBookmark = useCallback(
    async (bookmark: Bookmark) => {
      let thread = threads.find((entry) => entry.id === bookmark.thread_id) ?? null
      if (!thread) thread = await api.thread(bookmark.thread_id)
      setSelected(thread)
      setTerms([])
      setJump({ seq: bookmark.seq, messageId: bookmark.message_id, nonce: Date.now() })
    },
    [threads],
  )

  const jumpToMedia = useCallback((item: GalleryItem) => {
    setJump({ seq: item.seq, messageId: item.message_id, nonce: Date.now() })
  }, [])

  /** Clicking a photo in the chat means "show me this photo", not just "open the panel". */
  const openMediaInGallery = useCallback((mediaId: number) => {
    setFocusMediaId(mediaId)
    setPanel('media')
  }, [])

  // Keyboard shortcuts: ⌘K / Ctrl+K for search, Escape to close panels.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPanel((current) => (current === 'search' ? 'none' : 'search'))
      }
      if (event.key === 'Escape' && !showStats) setPanel('none')
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showStats])

  const headerSubtitle = useMemo(() => {
    if (!selected) return ''
    const parts: string[] = []
    parts.push(
      selected.is_group ? `${selected.participant_count} participants` : 'Direct message',
    )
    parts.push(`${formatNumber(selected.message_count)} messages`)
    if (selected.media_count) parts.push(`${formatNumber(selected.media_count)} media`)
    return parts.join(' · ')
  }, [selected])

  if (state && !state.has_data && !showWizard) {
    return (
      <SetupWizard
        dismissable={false}
        existing={state}
        onDone={() => {
          refreshState()
        }}
      />
    )
  }

  return (
    <div className="flex h-full">
      <Sidebar
        threads={threads}
        loading={loadingThreads}
        selectedId={selected?.id ?? null}
        filter={filter}
        sources={sources}
        onFilterChange={setFilter}
        onSourcesChange={setSources}
        onSelect={openThread}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-zinc-200 bg-white px-4 py-2.5 dark:border-zinc-800 dark:bg-zinc-900">
          {selected ? (
            <>
              <Avatar
                name={selected.is_group ? selected.title : (selected.others[0] ?? selected.title)}
                hue={selected.participants.find((p) => !p.is_owner)?.hue ?? 220}
                group={selected.is_group}
                size={34}
              />
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold">{selected.title}</h1>
                <p className="truncate text-xs text-zinc-500">{headerSubtitle}</p>
              </div>
            </>
          ) : (
            <div className="min-w-0">
              <h1 className="text-sm font-semibold">Messenger Archive</h1>
              <p className="text-xs text-zinc-500">
                {state
                  ? `${formatNumber(state.messages)} messages across ${formatNumber(state.threads)} conversations`
                  : 'Loading…'}
              </p>
            </div>
          )}

          <div className="ml-auto flex items-center gap-1">
            {selected && <TimeTravel thread={selected} onJump={(seq) => setJump({ seq, nonce: Date.now() })} />}

            <span className="mx-1 h-5 w-px bg-zinc-200 dark:bg-zinc-800" />

            <button
              type="button"
              onClick={() => setPanel(panel === 'search' ? 'none' : 'search')}
              className={`btn-ghost px-2 ${panel === 'search' ? 'bg-zinc-200 dark:bg-zinc-800' : ''}`}
              title="Search (⌘K)"
              aria-label="Search"
            >
              <Search size={16} />
            </button>
            <button
              type="button"
              disabled={!selected}
              onClick={() => setPanel(panel === 'media' ? 'none' : 'media')}
              className={`btn-ghost px-2 ${panel === 'media' ? 'bg-zinc-200 dark:bg-zinc-800' : ''}`}
              title="Shared media"
              aria-label="Shared media"
            >
              <Images size={16} />
            </button>
            <button
              type="button"
              disabled={!selected}
              onClick={() => setShowStats(true)}
              className="btn-ghost px-2"
              title="Chat statistics"
              aria-label="Chat statistics"
            >
              <BarChart3 size={16} />
            </button>
            <button
              type="button"
              onClick={() => setPanel(panel === 'bookmarks' ? 'none' : 'bookmarks')}
              className={`btn-ghost px-2 ${panel === 'bookmarks' ? 'bg-zinc-200 dark:bg-zinc-800' : ''}`}
              title="Saved memories"
              aria-label="Saved memories"
            >
              <Star size={16} />
            </button>

            <span className="mx-1 h-5 w-px bg-zinc-200 dark:bg-zinc-800" />

            <button
              type="button"
              onClick={() => setShowWizard(true)}
              className="btn-ghost px-2"
              title="Add more archives"
              aria-label="Add more archives"
            >
              <Plus size={16} />
            </button>
            <button
              type="button"
              onClick={toggleTheme}
              className="btn-ghost px-2"
              title={dark ? 'Light mode' : 'Dark mode'}
              aria-label={dark ? 'Light mode' : 'Dark mode'}
            >
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        {selected ? (
          <ChatView
            key={selected.id}
            thread={selected}
            jump={jump}
            terms={terms}
            onOpenMedia={openMediaInGallery}
            onBookmarkChange={() => setBookmarkToken((value) => value + 1)}
            onAnchorChange={panel === 'media' ? setChatAnchorTs : undefined}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-zinc-500">
            <Users size={32} className="opacity-30" />
            <p className="text-sm">Pick a conversation on the left.</p>
          </div>
        )}
      </main>

      {panel === 'search' && (
        <SearchPanel
          thread={selected}
          sources={sources}
          onOpenResult={openResult}
          onClose={() => setPanel('none')}
        />
      )}

      {panel === 'media' && selected && (
        <MediaGallery
          thread={selected}
          chatAnchorTs={chatAnchorTs}
          focusMediaId={focusMediaId}
          onFocusHandled={() => setFocusMediaId(null)}
          onClose={() => setPanel('none')}
          onJumpToMessage={jumpToMedia}
        />
      )}

      {panel === 'bookmarks' && (
        <BookmarksPanel
          refreshToken={bookmarkToken}
          onOpen={openBookmark}
          onClose={() => setPanel('none')}
        />
      )}

      {showStats && selected && (
        <StatsDialog thread={selected} onClose={() => setShowStats(false)} />
      )}

      {showWizard && (
        <SetupWizard
          dismissable
          existing={state}
          onClose={() => setShowWizard(false)}
          onDone={() => {
            setShowWizard(false)
            setSelected(null)
            refreshState()
            setFilter((value) => value) // nudge the thread list to refetch
          }}
        />
      )}
    </div>
  )
}
