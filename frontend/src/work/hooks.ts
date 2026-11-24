import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../i18n/lv'

/** Load data, refresh it on a timer while the page is open (backend is the source of truth), expose errors. */
export function useLoad<T>(load: () => Promise<T>, refreshMs = 0, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })
  const reload = useCallback(async () => {
    try {
      const value = await loadRef.current()
      setData(value)
      setError(null)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    void reload()
    if (!refreshMs) return
    const timer = window.setInterval(() => void reload(), refreshMs)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, refreshMs, ...deps])
  return { data, setData, error, loading, reload }
}

/** Seconds left until an ISO time, ticking every second (display only; the backend decides expiry). */
export function useSecondsLeft(iso: string | null | undefined): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!iso) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [iso])
  return iso ? Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000)) : 0
}

/** Runs an action, keeps a busy flag and the translated error. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (e) {
      setError(errorMessage(e))
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, setError, run }
}
