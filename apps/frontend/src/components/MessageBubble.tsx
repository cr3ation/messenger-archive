import { memo } from 'react'
import { FileText, ImageOff, Link2, Phone, Star, Volume2 } from 'lucide-react'
import { downloadUrl, mediaUrl, thumbUrl } from '../api'
import { formatBytes, formatDuration, formatTime, highlightTerms } from '../lib/format'
import type { MediaItem, Message } from '../types'
import { Avatar } from './Avatar'

interface Props {
  message: Message
  isGroup: boolean
  showSender: boolean
  terms: string[]
  highlighted: boolean
  onToggleBookmark: (message: Message) => void
  onOpenMedia: (mediaId: number) => void
}

/** A message that is nothing but emoji gets rendered large, like a real chat app. */
const EMOJI_ONLY = /^[\p{Extended_Pictographic}\p{Emoji_Component}\s]+$/u

function MediaGrid({ media, onOpen }: { media: MediaItem[]; onOpen: (id: number) => void }) {
  // Anything whose bytes never made it into the export is called out rather
  // than rendered as a broken image — most often an attachment Meta's own
  // exporter failed to fetch.
  const available = media.filter((item) => !item.is_missing)
  const unavailable = media.length - available.length

  const visual = available.filter((item) => ['photo', 'gif', 'sticker'].includes(item.kind))
  const videos = available.filter((item) => item.kind === 'video')
  const audio = available.filter((item) => item.kind === 'audio')
  const files = available.filter((item) => item.kind === 'file')

  return (
    <div className="mt-1 flex flex-col gap-1.5">
      {visual.length > 0 && (
        <div
          className={`grid gap-1 ${visual.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}
        >
          {visual.map((item) => {
            // Stickers are excluded from the gallery, so there is nothing to
            // open them in — render them as plain images rather than buttons
            // that would do nothing.
            const openable = item.kind !== 'sticker'
            const image = (
              <img
                src={thumbUrl(item.id, visual.length === 1 ? 640 : 320)}
                alt={item.filename ?? ''}
                loading="lazy"
                className={`w-full object-cover transition-transform duration-200 ${
                  openable ? 'group-hover:scale-[1.02]' : ''
                } ${visual.length === 1 ? 'max-h-80' : 'h-36'}`}
              />
            )

            return openable ? (
              <button
                key={item.id}
                type="button"
                onClick={() => onOpen(item.id)}
                className="group relative overflow-hidden rounded-lg bg-black/10 dark:bg-black/30"
              >
                {image}
              </button>
            ) : (
              <div
                key={item.id}
                className="relative overflow-hidden rounded-lg bg-black/10 dark:bg-black/30"
              >
                {image}
              </div>
            )
          })}
        </div>
      )}

      {videos.map((item) => (
        <video
          key={item.id}
          src={mediaUrl(item.id)}
          controls
          preload="metadata"
          className="max-h-80 w-full rounded-lg bg-black"
        />
      ))}

      {audio.map((item) => (
        <div key={item.id} className="flex items-center gap-2 rounded-lg bg-black/5 p-2 dark:bg-white/5">
          <Volume2 size={16} className="shrink-0 opacity-60" />
          <audio src={mediaUrl(item.id)} controls preload="none" className="h-8 w-full" />
        </div>
      ))}

      {files.map((item) => (
        <a
          key={item.id}
          href={downloadUrl(item.id)}
          className="flex items-center gap-2 rounded-lg bg-black/5 p-2 text-sm hover:bg-black/10 dark:bg-white/5 dark:hover:bg-white/10"
        >
          <FileText size={16} className="shrink-0 opacity-60" />
          <span className="truncate">{item.filename}</span>
          <span className="ml-auto shrink-0 text-xs opacity-60">{formatBytes(item.size_bytes)}</span>
        </a>
      ))}

      {unavailable > 0 && (
        <p
          className="flex items-center gap-1.5 rounded-lg bg-black/5 px-2 py-1.5 text-xs italic opacity-70 dark:bg-white/5"
          title="Meta's export did not include the file"
        >
          <ImageOff size={13} className="shrink-0" />
          {unavailable === 1
            ? 'An attachment could not be exported'
            : `${unavailable} attachments could not be exported`}
        </p>
      )}
    </div>
  )
}

function MessageBubbleImpl({
  message,
  isGroup,
  showSender,
  terms,
  highlighted,
  onToggleBookmark,
  onOpenMedia,
}: Props) {
  const own = message.is_own
  const body = message.content ?? ''
  const jumbo = body.length > 0 && body.length <= 12 && EMOJI_ONLY.test(body)
  const parts = terms.length ? highlightTerms(body, terms) : [{ text: body, hit: false }]

  return (
    <div
      className={`group flex w-full gap-2 px-4 ${own ? 'flex-row-reverse' : 'flex-row'} ${
        showSender ? 'mt-3' : 'mt-0.5'
      } ${highlighted ? 'animate-highlight-pulse' : ''}`}
    >
      {isGroup && !own ? (
        showSender ? (
          <Avatar name={message.sender} hue={message.sender_hue} size={32} className="mt-5" />
        ) : (
          <div className="w-8 shrink-0" />
        )
      ) : null}

      <div className={`flex max-w-[min(46rem,78%)] flex-col ${own ? 'items-end' : 'items-start'}`}>
        {showSender && isGroup && !own && (
          <span className="mb-0.5 px-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            {message.sender}
          </span>
        )}

        <div className={`flex items-end gap-1.5 ${own ? 'flex-row-reverse' : 'flex-row'}`}>
          <div
            className={`relative rounded-2xl px-3.5 py-2 text-[0.9375rem] leading-relaxed shadow-sm ${
              own
                ? 'rounded-br-md bg-indigo-600 text-white'
                : 'rounded-bl-md bg-white text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
            } ${jumbo ? 'bg-transparent px-1 shadow-none dark:bg-transparent' : ''}`}
          >
            {message.is_unsent ? (
              <span className="italic opacity-60">Message was unsent</span>
            ) : (
              <>
                {body && (
                  <p
                    className={`whitespace-pre-wrap break-words ${
                      jumbo ? 'text-5xl leading-tight' : ''
                    }`}
                  >
                    {parts.map((part, index) =>
                      part.hit ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
                    )}
                  </p>
                )}

                {message.share_link && (
                  <a
                    href={message.share_link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className={`mt-1 flex items-center gap-1.5 text-sm underline underline-offset-2 ${
                      own ? 'text-indigo-100' : 'text-indigo-600 dark:text-indigo-400'
                    }`}
                  >
                    <Link2 size={14} className="shrink-0" />
                    <span className="truncate">{message.share_text || message.share_link}</span>
                  </a>
                )}

                {message.call_duration !== null && (
                  <span className="flex items-center gap-1.5 text-sm opacity-80">
                    <Phone size={14} />
                    Call · {formatDuration(message.call_duration)}
                  </span>
                )}

                {message.media.length > 0 && (
                  <MediaGrid media={message.media} onOpen={onOpenMedia} />
                )}
              </>
            )}

            {message.reactions.length > 0 && (
              <div
                className={`absolute -bottom-2.5 flex gap-0.5 rounded-full border border-zinc-200 bg-white px-1.5 py-0.5 text-xs shadow-sm dark:border-zinc-700 dark:bg-zinc-900 ${
                  own ? 'left-1' : 'right-1'
                }`}
                title={message.reactions.map((r) => `${r.emoji} ${r.actor}`).join('\n')}
              >
                {[...new Set(message.reactions.map((r) => r.emoji))].slice(0, 4).map((emoji) => (
                  <span key={emoji}>{emoji}</span>
                ))}
                {message.reactions.length > 1 && (
                  <span className="text-zinc-500">{message.reactions.length}</span>
                )}
              </div>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1 pb-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              onClick={() => onToggleBookmark(message)}
              title={message.bookmarked ? 'Remove bookmark' : 'Save as a memory'}
              aria-label={message.bookmarked ? 'Remove bookmark' : 'Save as a memory'}
              className="rounded p-1 text-zinc-400 hover:bg-zinc-200 hover:text-amber-500 dark:hover:bg-zinc-800"
            >
              <Star
                size={14}
                className={message.bookmarked ? 'fill-amber-400 text-amber-400' : ''}
              />
            </button>
          </div>
        </div>

        <span
          className={`mt-1 px-1 text-[0.6875rem] tabular-nums text-zinc-400 dark:text-zinc-500 ${
            message.reactions.length ? 'mt-3' : ''
          }`}
        >
          {formatTime(message.ts)}
          {message.bookmarked && <Star size={10} className="ml-1 inline fill-amber-400 text-amber-400" />}
        </span>
      </div>
    </div>
  )
}

export const MessageBubble = memo(MessageBubbleImpl)
