import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from '../../../i18n/lv'
import type { Page } from '../../../types/api'

/**
 * A cursor-paged list (`{items, next_cursor}`): the first page reloads whenever `fetchPage` changes (new
 * filters) or on `retry`; `loadMore` appends the next page. State is set only when a request settles.
 */
export function usePaged<T>(fetchPage: (cursor: string | null) => Promise<Page<T>>) {
  const [items, setItems] = useState<T[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchPage(null)
      .then((page) => {
        if (cancelled) return
        setItems(page.items)
        setCursor(page.next_cursor)
        setError(null)
      })
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [fetchPage, reloadKey])

  /** Call before changing a filter, so the old list is not shown as the new result. */
  const beginLoading = useCallback(() => {
    setLoading(true)
    setError(null)
  }, [])

  const retry = useCallback(() => {
    beginLoading()
    setReloadKey((k) => k + 1)
  }, [beginLoading])

  const loadMore = useCallback(async () => {
    setLoading(true)
    try {
      const page = await fetchPage(cursor)
      setItems((prev) => [...prev, ...page.items])
      setCursor(page.next_cursor)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [cursor, fetchPage])

  return { items, hasMore: cursor !== null, loading, error, beginLoading, retry, loadMore }
}
