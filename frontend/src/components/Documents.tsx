import { useEffect, useRef, useState } from 'react'
import type { FileBlob } from '../api/client'
import { errorMessage, t } from '../i18n/lv'
import { rigaDateTime } from '../i18n/format'
import type { Attachment } from '../types/masters'

const td = t.documents

/** Images browsers show inline; PDF and HEIC are only downloaded (owner decision, step 4.6.5). */
const VIEWABLE = new Set(['image/jpeg', 'image/png', 'image/webp'])

interface Viewing {
  fileId: string
  url: string
}

/**
 * Evidence files through an authorised route only (admin or owning master). Images are viewed from a Blob URL
 * that is revoked when the view closes, another image opens or the card unmounts. PDF and HEIC are only
 * downloaded (owner decision, step 4.6.5): a download's Blob URL is revoked right after the click.
 */
export function Documents({
  submission,
  fetchFile,
}: {
  submission: { qualification_name: string; files: Attachment[] }
  /** The authorised route for this submission's files (admin or the owning master). */
  fetchFile: (fileId: string, mode: 'view' | 'download') => Promise<FileBlob>
}) {
  const [viewing, setViewing] = useState<Viewing | null>(null)
  const [fetching, setFetching] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    if (!viewing) return
    const { url } = viewing
    return () => URL.revokeObjectURL(url)
  }, [viewing])

  async function open(file: Attachment, mode: 'view' | 'download') {
    if (inFlight.current) return
    inFlight.current = true
    setFetching(`${file.id}:${mode}`)
    setError(null)
    try {
      const { blob, filename } = await fetchFile(file.id, mode)
      if (!alive.current) return // the card is gone: never create a URL nobody will revoke
      const url = URL.createObjectURL(blob)
      if (mode === 'view') {
        setViewing({ fileId: file.id, url })
      } else {
        const link = document.createElement('a')
        link.href = url
        link.download = filename ?? file.id
        link.click()
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      if (alive.current) setError(errorMessage(err))
    } finally {
      inFlight.current = false
      if (alive.current) setFetching(null)
    }
  }

  if (submission.files.length === 0) return <p className="muted">{td.noFiles}</p>
  return (
    <div className="documents">
      <h3>{td.files}</h3>
      <ul className="plain">
        {submission.files.map((file, index) => {
          const name = `${td.file(index + 1)} (${submission.qualification_name})`
          return (
            <li key={file.id} className="document">
              <span>
                {td.file(index + 1)} · {file.mime_type} · {Math.max(1, Math.round(file.size_bytes / 1024))} KB ·{' '}
                {rigaDateTime(file.uploaded_at)}
              </span>
              <span className="actions">
                {VIEWABLE.has(file.mime_type) ? (
                  <button
                    aria-busy={fetching === `${file.id}:view`}
                    type="button"
                    className="button-secondary"
                    aria-label={`${td.view}: ${name}`}
                    disabled={fetching !== null}
                    onClick={() => void open(file, 'view')}
                  >
                    {fetching === `${file.id}:view` ? td.fileLoading : td.view}
                  </button>
                ) : (
                  <span className="muted">{td.notViewable}</span>
                )}
                <button
                  aria-busy={fetching === `${file.id}:download`}
                  type="button"
                  className="button-secondary"
                  aria-label={`${td.download}: ${name}`}
                  disabled={fetching !== null}
                  onClick={() => void open(file, 'download')}
                >
                  {fetching === `${file.id}:download` ? td.fileLoading : td.download}
                </button>
              </span>
            </li>
          )
        })}
      </ul>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {viewing && (
        <figure className="doc-view" aria-label={td.viewing}>
          <img src={viewing.url} alt={td.viewing} />
          <figcaption>
            <button type="button" className="button-secondary" onClick={() => setViewing(null)}>
              {td.closeView}
            </button>
          </figcaption>
        </figure>
      )}
    </div>
  )
}
