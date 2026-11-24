import { useCallback, useEffect, useRef, useState } from 'react'
import { adminMastersApi } from '../../../api/endpoints'
import { errorMessage, t } from '../../../i18n/lv'
import type { AdminCompetency, AdminMaster, BulkPreview, BulkPreviewItem, BulkRejectedItem } from '../../../types/masters'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { ACTIONS, BULK_VERIFY_MAX, decisionReasonText } from './decisions'

const tb = t.bulk

function errorCode(error: unknown): string {
  return typeof error === 'object' && error && 'code' in error ? String(error.code) : ''
}

function rejectedItems(error: unknown): BulkRejectedItem[] {
  const details = typeof error === 'object' && error && 'details' in error ? error.details : null
  const items = details && typeof details === 'object' && 'items' in details ? details.items : null
  return Array.isArray(items) ? (items as BulkRejectedItem[]) : []
}

/** Competencies a verify button is offered for (the UX mirror in decisions.ts; the backend decides). */
function candidatesOf(master: AdminMaster): AdminCompetency[] {
  return master.competencies.filter((c) => ACTIONS.competencies[c.status]?.includes('verify'))
}

/** What the availability check was made for: a changed version or set means it is out of date. */
function signatureOf(candidates: AdminCompetency[]): string {
  return candidates.map((c) => `${c.service_id}:${c.version}`).join(',')
}

/** The backend's own preview, in chunks of its limit, for every candidate: which ones may be bulk-verified. */
async function checkAvailability(masterId: string, ids: string[]): Promise<Map<string, BulkPreviewItem>> {
  const found = new Map<string, BulkPreviewItem>()
  for (let i = 0; i < ids.length; i += BULK_VERIFY_MAX) {
    const preview = await adminMastersApi.bulkPreview(masterId, ids.slice(i, i + BULK_VERIFY_MAX))
    for (const item of preview.items) found.set(item.service_id, item)
  }
  return found
}

/**
 * Bulk competency verification (R-MST-14, Q-28, step 4.4.8): select → preview of exactly the selection →
 * explicit confirmation → apply that preview, all or nothing. Which competencies may be selected comes from
 * the backend preview (regulated services and other blockers are reported there), never from a frontend rule.
 */
export function BulkVerify({
  master,
  disabled,
  onApplied,
  reload,
}: {
  master: AdminMaster
  /** A single decision is in flight. */
  disabled: boolean
  onApplied: (card: AdminMaster) => void
  /** Reloads the card (after a refused bulk verification). */
  reload: () => Promise<void>
}) {
  const candidates = candidatesOf(master)
  const signature = signatureOf(candidates)
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checked, setChecked] = useState<{ signature: string; items: Map<string, BulkPreviewItem> } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [previewing, setPreviewing] = useState<string[] | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const stale = checked !== null && checked.signature !== signature
  const available = (id: string) => checked?.items.get(id)?.verifiable === true
  // Only candidates still on the card count (a single decision may have changed one meanwhile).
  const chosen = candidates.map((c) => c.service_id).filter((id) => selected.includes(id))

  async function check() {
    setOpen(true)
    setChecking(true)
    setError(null)
    setDone(null)
    const forSignature = signature
    try {
      const items = await checkAvailability(
        master.id,
        candidates.map((c) => c.service_id),
      )
      setChecked({ signature: forSignature, items })
      setSelected((prev) => prev.filter((id) => items.get(id)?.verifiable))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < BULK_VERIFY_MAX ? [...prev, id] : prev,
    )
  }

  function close() {
    setOpen(false)
    setChecked(null)
    setSelected([])
    setError(null)
  }

  if (candidates.length === 0 && !done) return null

  return (
    <div className="card bulk">
      <h3>{tb.title}</h3>
      {done && (
        <p role="status" className="notice notice-approved">
          {done}
        </p>
      )}
      {!open && candidates.length > 0 && (
        <>
          <p className="muted">{tb.intro}</p>
          <button type="button" className="button-secondary" disabled={disabled} onClick={() => void check()}>
            {tb.start}
          </button>
        </>
      )}
      {open && (
        <>
          {checking && <p role="status">{tb.checking}</p>}
          {error && (
            <p role="alert" className="error">
              {error}{' '}
              <button type="button" className="button-secondary" onClick={() => void check()}>
                {t.retry}
              </button>
            </p>
          )}
          {stale && !checking && (
            <p role="status" className="notice">
              {tb.stale}{' '}
              <button type="button" className="button-secondary" onClick={() => void check()}>
                {tb.recheck}
              </button>
            </p>
          )}
          {checked && !checking && (
            <fieldset className="bulk-select" disabled={stale || disabled}>
              <legend>{tb.legend}</legend>
              {!candidates.some((c) => available(c.service_id)) && <p className="muted">{tb.noneAvailable}</p>}
              <ul className="plain">
                {candidates.map((c) => {
                  const item = checked.items.get(c.service_id)
                  const full = !chosen.includes(c.service_id) && chosen.length >= BULK_VERIFY_MAX
                  return (
                    <li key={c.service_id}>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={chosen.includes(c.service_id)}
                          disabled={!available(c.service_id) || full}
                          onChange={() => toggle(c.service_id)}
                        />
                        <span>
                          <code>{c.w_id}</code> {c.name}
                        </span>
                      </label>
                      {item && !item.verifiable && (
                        <ul aria-label={`${tb.notAvailable}: ${c.w_id}`} className="reasons">
                          {item.reasons.map((r, i) => (
                            <li key={`${r.code}-${i}`}>{decisionReasonText(r)}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ul>
              {chosen.length >= BULK_VERIFY_MAX && <p className="hint">{tb.limit(BULK_VERIFY_MAX)}</p>}
              <div className="actions">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() =>
                    setSelected(candidates.map((c) => c.service_id).filter(available).slice(0, BULK_VERIFY_MAX))
                  }
                >
                  {tb.selectAll}
                </button>
                <button type="button" className="button-secondary" onClick={() => setSelected([])}>
                  {tb.clear}
                </button>
              </div>
            </fieldset>
          )}
          <div className="actions">
            <button
              type="button"
              disabled={chosen.length === 0 || stale || checking || disabled}
              onClick={() => setPreviewing(chosen)}
            >
              {tb.preview(chosen.length)}
            </button>
            <button type="button" className="button-secondary" onClick={close}>
              {tb.close}
            </button>
          </div>
        </>
      )}
      {previewing && (
        <BulkDialog
          masterId={master.id}
          selection={previewing}
          names={new Map(master.competencies.map((c) => [c.service_id, `${c.w_id} ${c.name}`]))}
          onApplied={(card, count) => {
            onApplied(card)
            setPreviewing(null)
            close()
            setDone(tb.applied(count))
          }}
          onConflict={reload}
          onClose={() => setPreviewing(null)}
        />
      )}
    </div>
  )
}

/**
 * The preview of exactly the selection and its confirmation. Only this preview can be applied; when the backend
 * refuses it (data changed since), nothing was verified: the card reloads, a new preview is shown and must be
 * confirmed again. Nothing is retried or applied automatically.
 */
function BulkDialog({
  masterId,
  selection,
  names,
  onApplied,
  onConflict,
  onClose,
}: {
  masterId: string
  selection: string[]
  names: Map<string, string>
  onApplied: (card: AdminMaster, count: number) => void
  onConflict: () => Promise<void>
  onClose: () => void
}) {
  const [preview, setPreview] = useState<BulkPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejected, setRejected] = useState<BulkRejectedItem[] | null>(null)
  const sending = useRef(false)

  // State is set only when the request settles, so the first load can run from an effect.
  const fetchPreview = useCallback(
    () =>
      adminMastersApi
        .bulkPreview(masterId, selection)
        .then(setPreview, (err: unknown) => setError(errorMessage(err)))
        .finally(() => setLoading(false)),
    [masterId, selection],
  )

  useEffect(() => {
    void fetchPreview()
  }, [fetchPreview])

  async function confirm() {
    if (!preview?.applicable || sending.current) return
    sending.current = true
    setApplying(true)
    setError(null)
    setRejected(null)
    try {
      const card = await adminMastersApi.bulkVerify(masterId, preview)
      onApplied(card, preview.items.length)
    } catch (err) {
      if (errorCode(err) === 'BULK_VERIFY_REJECTED') {
        // All or nothing: nothing was verified. The old preview is never offered again.
        setRejected(rejectedItems(err))
        setPreview(null)
        setLoading(true)
        try {
          await onConflict()
        } catch (reloadErr) {
          setError(errorMessage(reloadErr))
        }
        await fetchPreview()
      } else {
        setError(errorMessage(err))
      }
    } finally {
      sending.current = false
      setApplying(false)
    }
  }

  const label = (id: string, item?: BulkPreviewItem) =>
    item?.w_id ? `${item.w_id} ${item.name ?? ''}`.trim() : (names.get(id) ?? id)

  return (
    <ConfirmDialog
      title={tb.dialogTitle}
      confirmLabel={tb.confirm(selection.length)}
      busy={applying}
      confirmDisabled={!preview || loading || !preview.applicable}
      onConfirm={confirm}
      onCancel={onClose}
    >
      {rejected && (
        <div role="alert" className="notice">
          {tb.rejected}
          {rejected.length > 0 && (
            <ul aria-label={tb.rejectedItems} className="reasons">
              {rejected.map((r) => (
                <li key={r.service_id}>
                  {label(r.service_id)}: {r.reasons.map(decisionReasonText).join('; ')}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {loading && <p role="status">{tb.loading}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {preview && !loading && (
        <>
          <p>
            <strong>{tb.count(preview.items.length)}</strong>
          </p>
          <p className="notice">{tb.warning}</p>
          {!preview.applicable && (
            <p role="alert" className="error">
              {tb.notApplicable}
            </p>
          )}
          <ul aria-label={tb.selection} className="impact-services">
            {preview.items.map((item) => (
              <li key={item.service_id}>
                <strong>{label(item.service_id, item)}</strong>{' '}
                {item.verifiable ? (
                  <span className="ok">{tb.itemOk}</span>
                ) : (
                  <ul aria-label={`${tb.notAvailable}: ${label(item.service_id, item)}`} className="reasons">
                    {item.reasons.map((r, i) => (
                      <li key={`${r.code}-${i}`}>{decisionReasonText(r)}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </ConfirmDialog>
  )
}
