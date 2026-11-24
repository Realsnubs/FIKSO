import { useEffect, useState } from 'react'
import type { FileBlob } from '../api/client'
import { t } from '../i18n/lv'
import { useSecondsLeft } from './hooks'

export function Money({ value }: { value: string | null | undefined }) {
  return <>{value == null ? t.app.none : t.app.money(Number(value).toFixed(2))}</>
}

export function Countdown({ until, label }: { until: string; label: (time: string) => string }) {
  const left = useSecondsLeft(until)
  return (
    <span className="countdown" role="timer" aria-live="off">
      {label(t.app.countdown(Math.floor(left / 60), left % 60))}
    </span>
  )
}

/**
 * A private photo through the authorised API: fetched with the session, shown from a temporary Blob URL that is
 * revoked on unmount (CLAUDE.md: no public or pre-signed links).
 */
export function PrivatePhoto({ load, alt }: { load: () => Promise<FileBlob>; alt: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let current: string | null = null
    let cancelled = false
    load().then(
      ({ blob }) => {
        if (cancelled) return
        current = URL.createObjectURL(blob)
        setUrl(current)
      },
      () => !cancelled && setFailed(true),
    )
    return () => {
      cancelled = true
      if (current) URL.revokeObjectURL(current)
    }
    // The loader identity changes per render; the photo is loaded once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  if (failed) return <span className="muted">{t.app.none}</span>
  return url ? <img src={url} alt={alt} className="private-photo" /> : <span className="skeleton-box" aria-hidden="true" />
}

export function ErrorLine({ message }: { message: string | null }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null
}
