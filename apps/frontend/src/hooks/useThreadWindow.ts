import { useCallback } from 'react'
import { api } from '../api'
import type { Message } from '../types'
import { useSparsePages } from './useSparsePages'

export const PAGE_SIZE = 200

/**
 * Sparse access to a conversation, keyed by the `seq` the importer assigned.
 *
 * `seq` is a message's absolute position in its thread, so the chat view can
 * scroll straight to "July 2014" or a search hit without having loaded a single
 * message before it.
 */
export function useThreadWindow(threadId: number | null, messageCount: number) {
  const fetchPage = useCallback(
    async (offset: number, limit: number) => {
      if (threadId === null) return []
      const response = await api.messages(threadId, offset, limit)
      return response.messages
    },
    [threadId],
  )

  // Messages carry their own position, so trust it over the arrival order.
  const indexOf = useCallback((message: Message) => message.seq, [])

  return useSparsePages<Message>(threadId, messageCount, PAGE_SIZE, fetchPage, indexOf)
}
