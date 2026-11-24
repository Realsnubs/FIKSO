import { Skeleton } from '../../../components/Skeleton'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { adminMastersApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { Documents } from '../../../components/Documents'
import { StatusBadge } from '../../../components/StatusBadge'
import { errorMessage, t } from '../../../i18n/lv'
import type {
  AdminCompetency,
  AdminMaster,
  AdminSpecialisation,
  AdminSubmission,
  DecisionAction,
  DecisionGroup,
  DecisionReason,
} from '../../../types/masters'
import { ACTIONS, decisionReasonText, needsReason } from './decisions'
import { BulkVerify } from './BulkVerify'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { calendarDate, rigaDateTime } from '../../../i18n/format'
import { adminWorkApi } from '../../../api/work'
import { useLanguage } from '../../../i18n/LanguageContext'
import { useLoad } from '../../../work/hooks'
import { cityName, languageName, usePlaces } from '../../../work/placesData'

const tm = t.masterCard

interface Feedback {
  /** The item the message belongs to ("profile" or "group:key"). */
  item: string
  ok: boolean
  message: string
  /** Verification blockers from a 409 (`details.reasons`). */
  reasons?: DecisionReason[]
}

/** Runs one decision; resolves true when it was saved. */
type Decide = (item: string, call: () => Promise<AdminMaster>) => Promise<boolean>

function errorCode(error: unknown): string {
  return typeof error === 'object' && error && 'code' in error ? String(error.code) : ''
}

function blockers(error: unknown): DecisionReason[] | undefined {
  const details = typeof error === 'object' && error && 'details' in error ? error.details : null
  const reasons = details && typeof details === 'object' && 'reasons' in details ? details.reasons : null
  return Array.isArray(reasons) && reasons.length > 0 ? (reasons as DecisionReason[]) : undefined
}

/** `/admin/masters/:id` — a new ID starts a fresh card (no state carried over from another master). */
export function MasterDetailPage() {
  const { id = '' } = useParams()
  return <MasterCard key={id} id={id} />
}

/** The admin master card: everything needed for the decisions of step 4.4 (ARCHITECTURE §6b, R-MST-14..16). */
function MasterCard({ id }: { id: string }) {
  const [master, setMaster] = useState<AdminMaster | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const sending = useRef(false)
  usePageTitle(master?.full_name ?? t.masters.title)

  useEffect(() => {
    let cancelled = false
    adminMastersApi
      .get(id)
      .then(
        (found) => {
          if (cancelled) return
          setMaster(found)
          setLoadError(null)
        },
        (err: unknown) => !cancelled && setLoadError(err),
      )
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [id, reloadKey])

  /** The current card, without the loading state (the page stays as it is until the new card arrives). */
  const reload = useCallback(async () => setMaster(await adminMastersApi.get(id)), [id])

  const decide: Decide = useCallback(
    async (item, call) => {
      if (sending.current) return false // one decision at a time; a double click sends nothing more
      sending.current = true
      setBusy(item)
      setFeedback(null)
      try {
        // The decision answers with the card as committed, so the whole card shows the new state at once.
        setMaster(await call())
        setFeedback({ item, ok: true, message: tm.saved })
        return true
      } catch (err) {
        if (errorCode(err) === 'VERSION_CONFLICT') {
          // Someone decided meanwhile: show the current card; the admin decides again on fresh data.
          setFeedback({ item, ok: false, message: t.errors.VERSION_CONFLICT })
          try {
            await reload()
          } catch (reloadErr) {
            setFeedback({ item, ok: false, message: errorMessage(reloadErr) })
          }
        } else {
          const reasons = blockers(err)
          setFeedback({ item, ok: false, message: reasons ? tm.cannotVerify : errorMessage(err), reasons })
        }
        return false
      } finally {
        sending.current = false
        setBusy(null)
      }
    },
    [reload],
  )

  if (loading) {
    return (
      <section>
        <AdminNav />
        <Skeleton variant="page" />
      </section>
    )
  }
  if (!master) {
    const notFound = errorCode(loadError) === 'MASTER_NOT_FOUND' || errorCode(loadError) === 'VALIDATION_ERROR'
    return (
      <section>
        <AdminNav />
        <p role="alert" className="error">
          {notFound ? tm.notFound : errorMessage(loadError)}{' '}
          {!notFound && (
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                setLoading(true)
                setReloadKey((k) => k + 1)
              }}
            >
              {t.retry}
            </button>
          )}
        </p>
        <Link to="/admin/masters">{tm.back}</Link>
      </section>
    )
  }

  const shared = { masterId: master.id, busy, feedback, decide }
  return (
    <section className="master-card">
      <AdminNav />
      <Link to="/admin/masters">{tm.back}</Link>
      <h1>{master.full_name}</h1>
      <SectionNav master={master} />
      <General master={master} {...shared} />
      <WorkAndLanguages masterId={master.id} />

      <section id="sec-specialisations" aria-labelledby="mc-specialisations">
        <h2 id="mc-specialisations">{tm.specialisations}</h2>
        {master.specialisations.length === 0 ? (
          <p className="empty">{tm.noSpecialisations}</p>
        ) : (
          <ul className="user-list" aria-label={tm.specialisations}>
            {master.specialisations.map((s) => (
              <SpecialisationItem key={s.specialisation_id} item={s} {...shared} />
            ))}
          </ul>
        )}
      </section>

      <section id="sec-competencies" aria-labelledby="mc-competencies">
        <h2 id="mc-competencies">{tm.competencies}</h2>
        <BulkVerify master={master} disabled={busy !== null} onApplied={setMaster} reload={reload} />
        {master.competencies.length === 0 ? (
          <p className="empty">{tm.noCompetencies}</p>
        ) : (
          <ul className="user-list" aria-label={tm.competencies}>
            {master.competencies.map((c) => (
              <CompetencyItem
                key={c.service_id}
                item={c}
                specialisation={master.specialisations.find((s) => s.specialisation_id === c.specialisation_id)?.name}
                {...shared}
              />
            ))}
          </ul>
        )}
      </section>

      <section id="sec-qualifications" aria-labelledby="mc-qualifications">
        <h2 id="mc-qualifications">{tm.qualifications}</h2>
        {master.qualifications.length === 0 ? (
          <p className="empty">{tm.noQualifications}</p>
        ) : (
          <ul className="user-list" aria-label={tm.qualifications}>
            {master.qualifications.map((q) => (
              <SubmissionItem
                key={q.id}
                item={q}
                rule={master.qualification_types.find((r) => r.id === q.qualification_id)}
                {...shared}
              />
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}


/**
 * Jump links to the card's sections with how many entries each has and how many wait for a decision, so a long card
 * stays easy to scan. Every section stays on the page (nothing is hidden behind tabs).
 */
function SectionNav({ master }: { master: AdminMaster }) {
  const items = [
    { id: 'sec-general', label: tm.general, count: null, pending: master.approval_status === 'pending_approval' ? 1 : 0 },
    {
      id: 'sec-specialisations',
      label: tm.specialisations,
      count: master.specialisations.length,
      pending: master.specialisations.filter((x) => x.status === 'requested').length,
    },
    {
      id: 'sec-competencies',
      label: tm.competencies,
      count: master.competencies.length,
      pending: master.competencies.filter((x) => x.status === 'declared').length,
    },
    {
      id: 'sec-qualifications',
      label: tm.qualifications,
      count: master.qualifications.length,
      pending: master.qualifications.filter((x) => x.status === 'submitted').length,
    },
  ]
  return (
    <nav className="section-nav" aria-label={tm.sections}>
      {items.map((item) => (
        <a key={item.id} href={`#${item.id}`}>
          {item.label}
          {item.count !== null && <span className="muted">({item.count})</span>}
          {item.pending > 0 && <span className="pending">{tm.pendingCount(item.pending)}</span>}
        </a>
      ))}
    </nav>
  )
}

interface Shared {
  masterId: string
  busy: string | null
  feedback: Feedback | null
  decide: Decide
}

/** City and communication languages decide whether the master is matched at all (read-only for the admin). */
function WorkAndLanguages({ masterId }: { masterId: string }) {
  const tp = t.app.places
  const { language } = useLanguage()
  const { languages } = usePlaces()
  const { data, error } = useLoad(() => adminWorkApi.masterWork(masterId), 0, [masterId])
  return (
    <section id="sec-work" aria-labelledby="mc-work" className="card">
      <h2 id="mc-work">{tp.masterWork}</h2>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <dl className="facts">
            <dt>{tp.workCity}</dt>
            <dd>{cityName(data.work_city, language)}</dd>
            <dt>{tp.languages}</dt>
            <dd>{data.languages.length ? data.languages.map((code) => languageName(code, languages, language)).join(', ') : tp.none}</dd>
            <dt>{t.app.work.availability}</dt>
            <dd>
              {t.app.work.modes[data.availability_mode]}
              {data.is_busy && ` · ${t.app.work.busy}`}
            </dd>
          </dl>
          <p className={data.ready_for_matching ? 'muted' : 'notice'}>{data.ready_for_matching ? tp.ready : tp.notReady}</p>
        </>
      )}
    </section>
  )
}

function General({ master, masterId, busy, feedback, decide }: Shared & { master: AdminMaster }) {
  return (
    <section id="sec-general" aria-labelledby="mc-general" className="card">
      <h2 id="mc-general">{tm.general}</h2>
      <dl className="facts">
        <dt>{tm.email}</dt>
        <dd>{master.email}</dd>
        <dt>{tm.phone}</dt>
        <dd>{master.phone ?? '—'}</dd>
        <dt>{tm.account}</dt>
        <dd>
          <span className={master.user_status === 'blocked' ? 'badge badge-blocked' : 'badge badge-active'}>
            {t.status[master.user_status]}
          </span>
          {master.blocked_reason && ` · ${tm.blockedReason}: ${master.blocked_reason}`}
        </dd>
        <dt>{tm.profile}</dt>
        <dd>
          <StatusBadge status={master.approval_status} label={t.approval[master.approval_status]} />
        </dd>
        <dt>{tm.registered}</dt>
        <dd>{rigaDateTime(master.registered_at)}</dd>
        <dt>{tm.lastDecision}</dt>
        <dd>
          {master.decided_at ? rigaDateTime(master.decided_at) : tm.noDecision}
          {master.decision_reason && ` · ${tm.reason}: ${master.decision_reason}`}
        </dd>
      </dl>
      <Decisions
        item="profile"
        label={master.full_name}
        actions={ACTIONS.profile[master.approval_status] ?? []}
        final={false}
        confirmApprove
        busy={busy}
        feedback={feedback}
        onDecide={(action, reason) =>
          decide('profile', () =>
            action === 'approve'
              ? adminMastersApi.approveProfile(masterId, master.version)
              : adminMastersApi.rejectProfile(masterId, master.version, reason ?? ''),
          )
        }
      />
    </section>
  )
}

/** Shared by the three groups: the decision POST with the row's version (and the reason when required). */
function groupDecision(shared: Shared, group: DecisionGroup, key: string, version: number) {
  const item = `${group}:${key}`
  return {
    item,
    onDecide: (action: DecisionAction, reason?: string) =>
      shared.decide(item, () => adminMastersApi.decide(shared.masterId, group, key, action, version, reason)),
  }
}

/**
 * The row's latest decision. A re-application (owner decision 2026-11-03) is pending again but keeps the
 * previous decision on the row, so a pending row's decision is labelled as the previous one.
 */
function Decided({ at, reason, pending }: { at: string | null; reason: string | null; pending: boolean }) {
  if (!at) return null
  return (
    <div className="muted">
      {pending ? t.decisionHistory.previous : tm.decided}: {rigaDateTime(at)}
      {reason && ` · ${tm.reason}: ${reason}`}
    </div>
  )
}

function SpecialisationItem({ item, ...shared }: Shared & { item: AdminSpecialisation }) {
  const decision = groupDecision(shared, 'specialisations', item.specialisation_id, item.version)
  return (
    <li className="card">
      <div className="user-head">
        <strong>{item.name}</strong>
        <StatusBadge status={item.status} label={t.specialisationStatus[item.status]} />
      </div>
      <div className="muted">
        {tm.requested}: {rigaDateTime(item.requested_at)}
      </div>
      <Decided at={item.decided_at} reason={item.decision_reason} pending={item.status === 'requested'} />
      <Decisions
        {...decision}
        label={item.name}
        actions={ACTIONS.specialisations[item.status] ?? []}
        final
        busy={shared.busy}
        feedback={shared.feedback}
      />
    </li>
  )
}

function CompetencyItem({
  item,
  specialisation,
  ...shared
}: Shared & { item: AdminCompetency; specialisation: string | undefined }) {
  const decision = groupDecision(shared, 'competencies', item.service_id, item.version)
  return (
    <li className="card">
      <div className="user-head">
        <strong>
          <code>{item.w_id}</code> {item.name}
        </strong>
        <StatusBadge status={item.status} label={t.competencyStatus[item.status]} />
      </div>
      <div className="muted">
        {specialisation && `${specialisation} · `}
        {tm.requested}: {rigaDateTime(item.declared_at)}
      </div>
      {/* Eligibility reasons are not shown here: they are not what blocks a verification. The actual
          blockers come from the backend when a verification is attempted (409 details.reasons). */}
      <Decided at={item.decided_at} reason={item.decision_reason} pending={item.status === 'declared'} />
      <Decisions
        {...decision}
        label={`${item.w_id} ${item.name}`}
        actions={ACTIONS.competencies[item.status] ?? []}
        final
        busy={shared.busy}
        feedback={shared.feedback}
      />
    </li>
  )
}

function SubmissionItem({
  item,
  rule,
  ...shared
}: Shared & { item: AdminSubmission; rule: AdminMaster['qualification_types'][number] | undefined }) {
  const decision = groupDecision(shared, 'qualifications', item.id, item.version)
  return (
    <li className="card">
      <div className="user-head">
        <strong>{item.qualification_name}</strong>
        <StatusBadge status={item.status} label={t.submissionStatus[item.status]} />
        {item.expired && <span className="badge badge-blocked">{tm.expired}</span>}
        {!item.expired && item.expires_soon && <span className="badge badge-warning">{tm.expiresSoon}</span>}
      </div>
      <dl className="facts">
        <dt>{tm.documentNumber}</dt>
        <dd>{item.document_number ?? '—'}</dd>
        <dt>{tm.validUntil}</dt>
        <dd>{item.valid_until ? calendarDate(item.valid_until) : tm.noExpiry}</dd>
        <dt>{tm.submitted}</dt>
        <dd>{rigaDateTime(item.submitted_at)}</dd>
      </dl>
      <Decided at={item.decided_at} reason={item.decision_reason} pending={item.status === 'submitted'} />
      {rule && (
        <details className="rules">
          <summary>{tm.rules}</summary>
          <ul className="plain">
            {rule.requires_document && <li>{t.qualifications.requiresDocument}</li>}
            {rule.requires_document_number && <li>{t.qualifications.requiresDocumentNumber}</li>}
            {rule.requires_expiry_date && <li>{t.qualifications.requiresExpiry}</li>}
            {rule.max_validity_months !== null && (
              <li>
                {t.qualifications.maxValidity}: {rule.max_validity_months}
              </li>
            )}
          </ul>
          {rule.verifier_instructions && (
            <p>
              <strong>{tm.instructions}:</strong> {rule.verifier_instructions}
            </p>
          )}
        </details>
      )}
      <Documents
        submission={item}
        fetchFile={(fileId, mode) => adminMastersApi.file(shared.masterId, item.id, fileId, mode)}
      />
      <Decisions
        {...decision}
        label={item.qualification_name}
        actions={ACTIONS.qualifications[item.status] ?? []}
        final
        busy={shared.busy}
        feedback={shared.feedback}
      />
    </li>
  )
}

/**
 * Decision buttons of one item. Approve/verify is one click; reject/revoke opens a reason form that must be
 * confirmed. While any decision is in flight every button is disabled.
 */
function Decisions({
  item,
  label,
  actions,
  final,
  confirmApprove = false,
  busy,
  feedback,
  onDecide,
}: {
  item: string
  label: string
  actions: DecisionAction[]
  /** The rejection/revocation cannot be undone (owner decision, step 4.4). */
  final: boolean
  /** Approval is final too and is confirmed in a dialog first (the profile, owner decision 4.6.5). */
  confirmApprove?: boolean
  busy: string | null
  feedback: Feedback | null
  onDecide: (action: DecisionAction, reason?: string) => Promise<boolean>
}) {
  const [open, setOpen] = useState<DecisionAction | null>(null)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [clicked, setClicked] = useState<DecisionAction | null>(null)
  const mine = feedback?.item === item ? feedback : null
  const fieldId = `reason-${item}`

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!open) return
    const trimmed = reason.trim()
    if (!trimmed) {
      setReasonError(t.errors.REASON_REQUIRED)
      return
    }
    setReasonError(null)
    if (await onDecide(open, trimmed)) {
      setOpen(null)
      setReason('')
    }
  }

  return (
    <div className="decisions">
      {mine && (
        <div role={mine.ok ? 'status' : 'alert'} className={mine.ok ? 'notice-approved notice' : 'error'}>
          {mine.message}
          {mine.reasons && (
            <ul aria-label={tm.cannotVerify} className="reasons">
              {mine.reasons.map((r, i) => (
                <li key={`${r.code}-${i}`}>{decisionReasonText(r)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {actions.length > 0 && !open && (
        <div className="actions">
          {actions.map((action) => (
            <button
              key={action}
              type="button"
              className={needsReason(action) ? 'button-secondary' : undefined}
              aria-label={`${tm.actions[action]}: ${label}`}
              disabled={busy !== null}
              aria-busy={busy === item && clicked === action}
              onClick={() => {
                setClicked(action)
                if (needsReason(action)) {
                  setOpen(action)
                  setReasonError(null)
                } else if (action === 'approve' && confirmApprove) {
                  setConfirming(true)
                } else {
                  void onDecide(action)
                }
              }}
            >
              {busy === item && clicked === action ? tm.saving : tm.actions[action]}
            </button>
          ))}
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={tm.approveProfileTitle}
          text={tm.approveProfileText(label)}
          confirmLabel={tm.actions.approve}
          busy={busy === item}
          onConfirm={async () => {
            await onDecide('approve')
            setConfirming(false) // the result (saved, conflict, error) is shown at the item
          }}
          onCancel={() => setConfirming(false)}
        />
      )}
      {open && (
        <form className="reason-form" onSubmit={(e) => void submit(e)} noValidate>
          <label htmlFor={fieldId}>{tm.reasonLabel}</label>
          <textarea
            id={fieldId}
            value={reason}
            maxLength={1000}
            rows={3}
            aria-required="true"
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={`${fieldId}-hint`}
            autoFocus
            onChange={(e) => setReason(e.target.value)}
          />
          <div id={`${fieldId}-hint`} className="hint">
            {tm.reasonHint}
            {final && ` ${tm.finalWarning}`}
          </div>
          {reasonError && (
            <p role="alert" className="error">
              {reasonError}
            </p>
          )}
          <div className="actions">
            <button type="submit" className="button-danger" aria-busy={busy === item} disabled={busy !== null}>
              {busy === item ? tm.saving : tm.confirmActions[open]}
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={busy !== null}
              onClick={() => {
                setOpen(null)
                setReasonError(null)
              }}
            >
              {t.admin.cancel}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
