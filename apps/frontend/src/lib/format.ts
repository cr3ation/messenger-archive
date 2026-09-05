const HL_START = ''
const HL_END = ''

// en-GB rather than en-US: day-before-month and a 24-hour clock match how the
// timestamps read in the source data, and how Messenger renders them in Europe.
const LOCALE = 'en-GB'

export const dateTime = new Intl.DateTimeFormat(LOCALE, {
  dateStyle: 'long',
  timeStyle: 'short',
})
export const dayLong = new Intl.DateTimeFormat(LOCALE, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
export const timeOnly = new Intl.DateTimeFormat(LOCALE, {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})
export const monthYear = new Intl.DateTimeFormat(LOCALE, { month: 'long', year: 'numeric' })

export const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]
export const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const formatDay = (ts: number) => dayLong.format(new Date(ts))
export const formatTime = (ts: number) => timeOnly.format(new Date(ts))
export const formatDateTime = (ts: number) => dateTime.format(new Date(ts))

export function formatMonthKey(ym: string) {
  const [year, month] = ym.split('-')
  return `${MONTH_NAMES[Number(month) - 1]} ${year}`
}

/** Same calendar day? Used to decide where date separators go. */
export function isSameDay(a: number, b: number) {
  const first = new Date(a)
  const second = new Date(b)
  return (
    first.getFullYear() === second.getFullYear() &&
    first.getMonth() === second.getMonth() &&
    first.getDate() === second.getDate()
  )
}

/** Relative day label for the conversation list ("14:32", "Yesterday", "3 Mar 2019"). */
export function formatRelative(ts: number | null) {
  if (!ts) return ''
  const date = new Date(ts)
  const now = new Date()
  if (isSameDay(ts, now.getTime())) return timeOnly.format(date)

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (isSameDay(ts, yesterday.getTime())) return 'Yesterday'

  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getDate()} ${MONTH_NAMES[date.getMonth()]}`
  }
  return `${date.getDate()} ${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`
}

export function formatBytes(bytes: number | null | undefined) {
  if (bytes === null || bytes === undefined) return ''
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function formatDuration(seconds: number | null) {
  if (!seconds) return ''
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    return `${hours} h ${minutes % 60} min`
  }
  return minutes ? `${minutes} min ${rest} s` : `${rest} s`
}

export const formatNumber = (value: number) => new Intl.NumberFormat(LOCALE).format(value)

export interface TextPart {
  text: string
  hit: boolean
}

/**
 * Split a server snippet on its highlight sentinels.
 *
 * The backend wraps hits in U+0002/U+0003 instead of `<mark>` so that message
 * content — which is arbitrary user text from 19 years of chat — can never be
 * interpreted as markup. React renders each part as a text node.
 */
export function splitSnippet(snippet: string): TextPart[] {
  const parts: TextPart[] = []
  let rest = snippet

  while (rest.length) {
    const start = rest.indexOf(HL_START)
    if (start === -1) {
      parts.push({ text: rest, hit: false })
      break
    }
    if (start > 0) parts.push({ text: rest.slice(0, start), hit: false })

    const end = rest.indexOf(HL_END, start)
    if (end === -1) {
      parts.push({ text: rest.slice(start + 1), hit: false })
      break
    }
    parts.push({ text: rest.slice(start + 1, end), hit: true })
    rest = rest.slice(end + 1)
  }

  return parts.filter((part) => part.text.length > 0)
}

/** Client-side highlighting of search terms inside a full message body. */
export function highlightTerms(text: string, terms: string[]): TextPart[] {
  const usable = terms.filter((term) => term.trim().length > 0)
  if (!usable.length) return [{ text, hit: false }]

  const escaped = usable
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .sort((a, b) => b.length - a.length)
  const pattern = new RegExp(`(${escaped.join('|')})`, 'giu')

  return text
    .split(pattern)
    .filter((piece) => piece.length > 0)
    .map((piece) => ({
      text: piece,
      hit: usable.some((term) => term.toLowerCase() === piece.toLowerCase()),
    }))
}

export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (!words.length) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[words.length - 1][0]).toUpperCase()
}

/** Deterministic avatar colours derived from the hue the importer stored. */
export function avatarStyle(hue: number, dark = true) {
  return {
    backgroundColor: `hsl(${hue} 55% ${dark ? '28%' : '86%'})`,
    color: `hsl(${hue} 70% ${dark ? '82%' : '28%'})`,
  }
}
