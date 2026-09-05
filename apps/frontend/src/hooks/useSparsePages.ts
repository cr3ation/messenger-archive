import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Sparse, page-addressed access to a long ordered list.
 *
 * Both the chat log and the media gallery show collections far too large to
 * hold in memory — 58 000 messages, 4 500 photos in a single conversation — but
 * the total count is known from the database up front. That lets a virtualiser
 * render a correct scrollbar and jump to any absolute position immediately;
 * this hook then fills in only the pages the viewport actually touches.
 *
 * `resetKey` invalidates everything when the underlying list changes (another
 * conversation, another media filter), including requests still in flight.
 */
export function useSparsePages<T>(
  resetKey: string | number | null,
  total: number,
  pageSize: number,
  fetchPage: (offset: number, limit: number) => Promise<T[]>,
  indexOf: (item: T, offset: number, position: number) => number,
) {
  const store = useRef(new Map<number, T>())
  const pending = useRef(new Set<number>())
  const generation = useRef(0)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    store.current = new Map()
    pending.current = new Set()
    generation.current += 1
    setVersion((value) => value + 1)
  }, [resetKey])

  const ensureRange = useCallback(
    (start: number, end: number) => {
      if (resetKey === null || total <= 0) return

      const firstPage = Math.max(0, Math.floor(start / pageSize))
      const lastPage = Math.floor(Math.min(end, total - 1) / pageSize)
      const currentGeneration = generation.current

      for (let page = firstPage; page <= lastPage; page += 1) {
        const offset = page * pageSize
        if (pending.current.has(page) || store.current.has(offset)) continue
        pending.current.add(page)

        fetchPage(offset, pageSize)
          .then((items) => {
            if (currentGeneration !== generation.current) return
            items.forEach((item, position) =>
              store.current.set(indexOf(item, offset, position), item),
            )
            setVersion((value) => value + 1)
          })
          .catch(() => {
            pending.current.delete(page)
          })
      }
    },
    [resetKey, total, pageSize, fetchPage, indexOf],
  )

  const get = useCallback((index: number) => store.current.get(index), [])
  const has = useCallback((index: number) => store.current.has(index), [])

  const patch = useCallback((index: number, changes: Partial<T>) => {
    const existing = store.current.get(index)
    if (!existing) return
    store.current.set(index, { ...existing, ...changes })
    setVersion((value) => value + 1)
  }, [])

  return { get, has, patch, ensureRange, version }
}
