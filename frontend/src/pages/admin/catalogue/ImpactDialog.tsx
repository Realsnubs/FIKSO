import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { catalogueApi } from '../../../api/endpoints'
import { rigaTimestamp } from '../../../i18n/format'
import { errorMessage, t } from '../../../i18n/lv'
import type { BasisItem, ImpactRequest, ImpactResponse, ImpactService, ServiceState } from '../../../types/catalogue'
import { restoreFocus } from '../../../components/focus'
import { reasonText } from './state'

const ti = t.impact

/** A change that affects availability: previewed first, applied only with the preview's basis (R-CAT-18). */
export interface PendingChange {
  request: ImpactRequest
  /**
   * The real operation. It receives the basis of the preview the admin confirmed and, as `expected_version`,
   * the changed entry's version from that same basis — so a fresh preview also brings the current version.
   */
  apply: (basis: BasisItem[], version: number) => Promise<unknown>
}

function code(error: unknown): string {
  return typeof error === 'object' && error && 'code' in error ? String(error.code) : ''
}


/**
 * Preview → consequences → confirm → apply with `expected_basis`. Nothing is applied automatically: after
 * IMPACT_PREVIEW_OUTDATED a fresh preview is loaded and must be confirmed again; CATALOGUE_BUSY is shown and
 * only the admin retries. The backend computes everything shown here.
 */
export function ImpactDialog({
  change,
  onApplied,
  onConflict,
  onClose,
}: {
  change: PendingChange
  onApplied: () => void
  /** The catalogue changed meanwhile: refresh the tree behind the dialog (forms stay as they are). */
  onConflict: () => void
  onClose: () => void
}) {
  const [preview, setPreview] = useState<ImpactResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const sending = useRef(false)

  // State is set only when the request settles, so the first load can run from an effect.
  const fetchPreview = useCallback(
    () =>
      catalogueApi
        .previewImpact(change.request)
        .then(setPreview, (err: unknown) => setError(errorMessage(err)))
        .finally(() => setLoading(false)),
    [change.request],
  )

  useEffect(() => {
    void fetchPreview()
  }, [fetchPreview])

  async function reloadPreview() {
    setLoading(true)
    setPreview(null) // an outdated preview is never shown as current
    await fetchPreview()
  }

  // Focus moves into the dialog and returns to the control that opened it when the dialog closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    return () => restoreFocus(opener)
  }, [])

  async function confirm() {
    if (!preview || sending.current) return
    sending.current = true
    setConfirming(true)
    setError(null)
    setNotice(null)
    const { entity, id } = change.request
    const changed = preview.basis.find((item) => item.kind === entity && item.id === id)
    try {
      if (!changed) throw new Error('the preview basis lacks the changed entry')
      await change.apply(preview.basis, changed.version)
      onApplied()
    } catch (err) {
      const conflict = code(err)
      if (conflict === 'IMPACT_PREVIEW_OUTDATED' || conflict === 'VERSION_CONFLICT') {
        // Someone changed the catalogue: show the current tree and current consequences; confirm again.
        setNotice(conflict === 'VERSION_CONFLICT' ? t.errors.VERSION_CONFLICT : ti.outdated)
        onConflict()
        await reloadPreview()
      } else {
        setError(errorMessage(err))
      }
    } finally {
      sending.current = false
      setConfirming(false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !confirming) {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !dialogRef.current) return
    // Keep keyboard focus inside the dialog.
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'),
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="impact-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <h2 id="impact-title">{ti.title}</h2>
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {loading && <p role="status">{ti.loading}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {preview && !loading && <Consequences preview={preview} />}
        <div className="actions">
          <button
            aria-busy={confirming}
            type="button"
            className="button-danger"
            onClick={() => void confirm()}
            disabled={!preview || loading || confirming}
          >
            {confirming ? ti.applying : ti.confirm}
          </button>
          <button type="button" className="button-secondary" onClick={onClose} disabled={confirming}>
            {ti.cancel}
          </button>
        </div>
      </div>
    </div>
  )
}

function Consequences({ preview }: { preview: ImpactResponse }) {
  const byId = new Map(preview.services.map((s) => [s.service_id, s]))
  const named = (ids: string[]) => ids.map((id) => byId.get(id)).filter((s): s is ImpactService => Boolean(s))
  const losing = preview.masters.losing_eligibility
  return (
    <div className="impact">
      <section aria-labelledby="impact-changes">
        <h3 id="impact-changes">{ti.changes}</h3>
        <ServiceNames title={ti.stops} services={named(preview.stops_being_orderable)} />
        <ServiceNames title={ti.becomes} services={named(preview.becomes_orderable)} />
        {preview.stops_being_orderable.length === 0 && preview.becomes_orderable.length === 0 && (
          <p className="muted">{ti.noOrderableChange}</p>
        )}
      </section>

      <section aria-labelledby="impact-services">
        <h3 id="impact-services">{ti.services}</h3>
        <ul className="impact-services">
          {preview.services.map((service) => (
            <li key={service.service_id}>
              <strong>
                <code>{service.w_id}</code> {service.name}
              </strong>
              <div className="impact-states">
                <State label={ti.before} state={service.before} />
                <State label={ti.after} state={service.after} />
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="impact-masters">
        <h3 id="impact-masters">{ti.masters}</h3>
        <Counts title={ti.bySpecialisationStatus} counts={preview.masters.by_specialisation_status} labels={t.specialisationStatus} />
        <Counts title={ti.byCompetencyStatus} counts={preview.masters.by_competency_status} labels={t.competencyStatus} />
        <p>
          {ti.losing}: <strong>{losing.total}</strong>
        </p>
        {losing.items.length > 0 && (
          <>
            <ul aria-label={ti.losingList} className="plain">
              {losing.items.map((m) => (
                <li key={m.master_id}>{m.full_name}</li>
              ))}
            </ul>
            {losing.total > losing.items.length && (
              <p className="muted">{ti.shownOf(losing.items.length, losing.total)}</p>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="impact-requests">
        <h3 id="impact-requests">{ti.requests}</h3>
        {/* null means "not known yet", never zero (owner decision 2, step 4.5). */}
        <p className="muted">{preview.open_requests === null ? ti.requestsLater : String(preview.open_requests)}</p>
      </section>

      <p className="muted">{ti.snapshot(rigaTimestamp(preview.computed_at))}</p>
    </div>
  )
}

function ServiceNames({ title, services }: { title: string; services: ImpactService[] }) {
  if (services.length === 0) return null
  return (
    <>
      <p>
        <strong>{title}</strong>
      </p>
      <ul aria-label={title} className="plain">
        {services.map((s) => (
          <li key={s.service_id}>
            <code>{s.w_id}</code> {s.name}
          </li>
        ))}
      </ul>
    </>
  )
}

function State({ label, state }: { label: string; state: ServiceState }) {
  return (
    <div className="impact-state">
      <span className="muted">{label}:</span>{' '}
      <span className={state.orderable ? 'ok' : 'error'}>
        {state.orderable ? t.catalogue.orderable : t.catalogue.notOrderable}
      </span>{' '}
      · {t.catalogue.eligibleMasters}: {state.eligible_masters}
      {state.reasons.length > 0 && (
        <ul aria-label={`${label}: ${t.catalogue.notOrderableReasons}`} className="reasons">
          {state.reasons.map((reason) => (
            <li key={reason.code}>{reasonText(reason)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Counts({
  title,
  counts,
  labels,
}: {
  title: string
  counts: Record<string, number>
  labels: Record<string, string>
}) {
  const entries = Object.entries(counts)
  return (
    <p>
      {title}:{' '}
      {entries.length === 0 ? (
        <span className="muted">{ti.none}</span>
      ) : (
        entries.map(([status, count]) => `${labels[status] ?? status} ${count}`).join(', ')
      )}
    </p>
  )
}
