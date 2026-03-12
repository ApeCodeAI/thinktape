import { useState, useEffect, useCallback } from 'react'
import { fetchNotes } from '@/lib/api'
import type { Note } from '@/types'

interface UseNotesOptions {
  type?: string
  tag?: string
  q?: string
  date?: string
  size?: number
}

export function useNotes(options: UseNotesOptions = {}) {
  const [notes, setNotes] = useState<Note[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)

  const size = options.size || 30

  // Reset when filters change
  useEffect(() => {
    setNotes([])
    setPage(1)
    setHasMore(true)
    setInitialLoading(true)
  }, [options.type, options.tag, options.q, options.date])

  // Fetch notes for current page
  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const res = await fetchNotes({
          page,
          size,
          type: options.type,
          tag: options.tag,
          q: options.q,
          date: options.date,
        })
        if (!cancelled) {
          setNotes(prev => page === 1 ? res.notes : [...prev, ...res.notes])
          setTotal(res.total)
          setHasMore(res.has_more)
        }
      } catch {
        // ignore errors
      } finally {
        if (!cancelled) {
          setLoading(false)
          setInitialLoading(false)
        }
      }
    }

    load()
    return () => { cancelled = true }
  }, [page, size, options.type, options.tag, options.q, options.date])

  const loadMore = useCallback(() => {
    if (!loading && hasMore) {
      setPage(p => p + 1)
    }
  }, [loading, hasMore])

  const refresh = useCallback(() => {
    setNotes([])
    setPage(1)
    setHasMore(true)
    setInitialLoading(true)
  }, [])

  return { notes, total, hasMore, loading, initialLoading, loadMore, refresh }
}
