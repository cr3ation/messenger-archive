import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, CornerUpRight, Download, X } from 'lucide-react'
import { downloadUrl, mediaUrl } from '../api'
import { formatBytes, formatDateTime, formatNumber } from '../lib/format'
import type { GalleryItem } from '../types'

interface Props {
  /** Absolute position in the gallery, not an index into a loaded subset. */
  index: number
  total: number
  getItem: (index: number) => GalleryItem | undefined
  /** Ask the gallery to load pages around a position before stepping into them. */
  onRequestRange: (start: number, end: number) => void
  onIndexChange: (index: number) => void
  onClose: () => void
  onJumpToMessage: (item: GalleryItem) => void
}

export function Lightbox({
  index,
  total,
  getItem,
  onRequestRange,
  onIndexChange,
  onClose,
  onJumpToMessage,
}: Props) {
  const item = getItem(index)
  const [loading, setLoading] = useState(true)

  const step = useCallback(
    (delta: number) => {
      const next = index + delta
      if (next < 0 || next >= total) return
      setLoading(true)
      // Addressing by absolute position means arrowing through all 4 500 photos
      // works; the surrounding pages are fetched as you approach them.
      onRequestRange(Math.max(0, next - 20), next + 20)
      onIndexChange(next)
    },
    [index, total, onIndexChange, onRequestRange],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowLeft') step(-1)
      if (event.key === 'ArrowRight') step(1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, step])

  const isVideo = item?.kind === 'video'
  const isAudio = item?.kind === 'audio'
  const isFile = item?.kind === 'file'

  return (
    <div
      className="fixed inset-0 z-50 flex animate-fade-in flex-col bg-black/90 backdrop-blur-sm"
      role="dialog"
      aria-modal
    >
      <header className="flex items-center gap-3 px-4 py-3 text-white">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{item?.filename ?? 'Loading…'}</p>
          <p className="text-xs text-white/60">
            {item ? (
              <>
                {item.sender} · {formatDateTime(item.ts)}
                {item.size_bytes ? ` · ${formatBytes(item.size_bytes)}` : ''}
              </>
            ) : null}
          </p>
        </div>

        <span className="ml-auto shrink-0 text-xs tabular-nums text-white/60">
          {formatNumber(index + 1)} / {formatNumber(total)}
        </span>

        {item && (
          <>
            <button
              type="button"
              onClick={() => onJumpToMessage(item)}
              className="btn rounded-lg bg-white/10 px-3 text-white hover:bg-white/20"
              title="Jump to the message"
            >
              <CornerUpRight size={15} />
              <span className="hidden sm:inline">To the message</span>
            </button>

            <a
              href={downloadUrl(item.id)}
              className="btn rounded-lg bg-white/10 px-2.5 text-white hover:bg-white/20"
              title="Download"
            >
              <Download size={15} />
            </a>
          </>
        )}

        <button
          type="button"
          onClick={onClose}
          className="btn rounded-lg bg-white/10 px-2.5 text-white hover:bg-white/20"
          aria-label="Close"
        >
          <X size={15} />
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1 items-center justify-center px-4 pb-6">
        {index > 0 && (
          <button
            type="button"
            onClick={() => step(-1)}
            className="absolute left-4 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
            aria-label="Previous"
          >
            <ChevronLeft size={22} />
          </button>
        )}

        {!item ? (
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-white" />
        ) : isVideo ? (
          <video
            key={item.id}
            src={mediaUrl(item.id)}
            controls
            autoPlay
            className="max-h-full max-w-full rounded-lg"
          />
        ) : isAudio ? (
          <audio key={item.id} src={mediaUrl(item.id)} controls autoPlay className="w-96" />
        ) : isFile ? (
          <a
            href={downloadUrl(item.id)}
            className="rounded-xl bg-white/10 px-6 py-8 text-center text-white hover:bg-white/20"
          >
            <Download size={32} className="mx-auto mb-3" />
            {item.filename}
          </a>
        ) : (
          <>
            {loading && (
              <div className="absolute h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-white" />
            )}
            <img
              key={item.id}
              src={mediaUrl(item.id)}
              alt={item.filename ?? ''}
              onLoad={() => setLoading(false)}
              className="max-h-full max-w-full rounded-lg object-contain"
            />
          </>
        )}

        {index < total - 1 && (
          <button
            type="button"
            onClick={() => step(1)}
            className="absolute right-4 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
            aria-label="Next"
          >
            <ChevronRight size={22} />
          </button>
        )}
      </div>
    </div>
  )
}
