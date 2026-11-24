import { Skeleton } from '../../components/Skeleton'
import { usePageTitle } from '../../i18n/usePageTitle'
import { useCallback, useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { masterApi } from '../../api/endpoints'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Documents } from '../../components/Documents'
import { MasterNav } from '../../components/MasterNav'
import { StatusBadge } from '../../components/StatusBadge'
import { calendarDate, rigaDateTime, sentence } from '../../i18n/format'
import { errorMessage, t } from '../../i18n/lv'
import type {
  Capabilities,
  Competency,
  MasterCatalogue,
  MasterCatalogueSpecialisation,
  QualificationType,
  SpecialisationApplication,
  Submission,
} from '../../types/capabilities'
import type { DecisionReason } from '../../types/masters'
import { decisionReasonText } from '../admin/masters/decisions'
import { ACCEPT, fileProblems, missingFields } from './uploads'

const tc = t.capabilities

/**
 * What the master may do with each status. UX only — it mirrors the backend (WITHDRAWABLE and `_reopen`, owner
 * decisions "Master withdrawals" and "Admin decisions" 6) so impossible actions are not offered; the backend
 * checks every request again (CANNOT_WITHDRAW, *_ALREADY_EXISTS, MASTER_PROFILE_REJECTED).
 */
const WITHDRAWABLE = { specialisation: 'requested', competency: 'declared', qualification: 'submitted' } as const
const REAPPLICABLE = new Set(['rejected', 'revoked', 'withdrawn'])
/** Services are offered under requested or approved specialisations (backend: SPECIALISATION_NOT_REQUESTED). */
const OPEN_SPECIALISATION = new Set(['requested', 'approved'])

interface Feedback {
  item: string
  ok: boolean
  message: string
}

/** Runs one change; resolves true when it was saved. */
type Run = (item: string, call: () => Promise<unknown>, okMessage?: string) => Promise<boolean>

interface Withdrawal {
  item: string
  name: string
  call: () => Promise<unknown>
}

interface Shared {
  readOnly: boolean
  busy: string | null
  feedback: Feedback | null
  run: Run
  askWithdraw: (withdrawal: Withdrawal) => void
}

/** Which qualification types a specialisation's card shows, and for what (only configured requirements). */
interface Requirement {
  id: string
  /** The specialisation itself requires it (all its services), or these services do. */
  wholeSpecialisation: boolean
  services: string[]
}

/**
 * The qualification requirements the catalogue states for a specialisation and its services
 * (`qualification_ids`, active types only). Nothing else links a qualification to a specialisation.
 */
function requirementsOf(spec: MasterCatalogueSpecialisation | undefined): Requirement[] {
  if (!spec) return []
  const found = new Map<string, Requirement>()
  for (const id of spec.qualification_ids) found.set(id, { id, wholeSpecialisation: true, services: [] })
  for (const service of spec.services) {
    for (const id of service.qualification_ids) {
      const entry = found.get(id) ?? { id, wholeSpecialisation: false, services: [] }
      entry.services.push(service.w_id)
      found.set(id, entry)
    }
  }
  return [...found.values()]
}

/**
 * "Manas specializācijas" (R-MST-08..16, ARCHITECTURE §6b): the master's own data only. Each specialisation card
 * holds its services (competencies) and the qualification documents its requirements name; the backend entities
 * stay separate.
 */
export function MasterCapabilitiesPage() {
  usePageTitle(tc.title)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [catalogue, setCatalogue] = useState<MasterCatalogue | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [withdrawal, setWithdrawal] = useState<Withdrawal | null>(null)
  const [adding, setAdding] = useState(false)
  const sending = useRef(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([masterApi.capabilities(), masterApi.catalogue()])
      .then(
        ([own, offered]) => {
          if (cancelled) return
          setCaps(own)
          setCatalogue(offered)
          setLoadError(null)
        },
        (err: unknown) => !cancelled && setLoadError(errorMessage(err)),
      )
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  /** Statuses, eligibility reasons and history come only from GET /capabilities, so it is read after each change. */
  const refresh = useCallback(async () => {
    const [own, offered] = await Promise.all([masterApi.capabilities(), masterApi.catalogue()])
    setCaps(own)
    setCatalogue(offered)
  }, [])

  const run: Run = useCallback(
    async (item, call, okMessage = tc.saved) => {
      if (sending.current) return false // one change at a time; a double click sends nothing more
      sending.current = true
      setBusy(item)
      setFeedback(null)
      try {
        await call()
        setFeedback({ item, ok: true, message: okMessage })
        await refresh().catch(() => undefined) // the change is saved even if the re-read fails
        return true
      } catch (err) {
        setFeedback({ item, ok: false, message: errorMessage(err) })
        // A conflict means the shown state is outdated (e.g. the profile was rejected meanwhile): re-read it.
        if (err instanceof ApiError && err.status === 409) await refresh().catch(() => undefined)
        return false
      } finally {
        sending.current = false
        setBusy(null)
      }
    },
    [refresh],
  )

  if (loading) {
    return (
      <section>
        <MasterNav />
        <Skeleton variant="page" />
      </section>
    )
  }
  if (!caps || !catalogue) {
    return (
      <section>
        <MasterNav />
        <p role="alert" className="error">
          {loadError ?? t.errors.generic}{' '}
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
        </p>
      </section>
    )
  }

  const readOnly = caps.approval_status === 'rejected'
  const shared: Shared = { readOnly, busy, feedback, run, askWithdraw: setWithdrawal }
  const offered = new Map(catalogue.specialisations.map((s) => [s.id, s]))
  // Pending and approved specialisations first; decided-against ones after them (display order only).
  const specs = [...caps.specialisations].sort(
    (a, b) => Number(!OPEN_SPECIALISATION.has(a.status)) - Number(!OPEN_SPECIALISATION.has(b.status)),
  )
  const ownSpecIds = new Set(caps.specialisations.map((s) => s.specialisation_id))
  const otherCompetencies = caps.competencies.filter((c) => !ownSpecIds.has(c.specialisation_id))
  const shownTypes = new Set(specs.flatMap((s) => requirementsOf(offered.get(s.specialisation_id)).map((r) => r.id)))

  return (
    <section className="master-card">
      <MasterNav />
      <div className="page-head">
        <h1>{tc.title}</h1>
        {!readOnly && (
          <button type="button" onClick={() => setAdding(true)}>
            {tc.addSpecialisation}
          </button>
        )}
      </div>
      <ProfileStatus caps={caps} />
      {!adding && <ItemFeedback item="specialisation:new" feedback={feedback} />}

      {specs.length === 0 ? (
        <div className="card empty">
          <p>{tc.noSpecialisations}</p>
          {!readOnly && <p className="muted">{tc.noSpecialisationsHint}</p>}
        </div>
      ) : (
        <ul className="spec-cards" aria-label={tc.title}>
          {specs.map((s) => (
            <SpecialisationCard
              key={s.specialisation_id}
              application={s}
              offered={offered.get(s.specialisation_id)}
              caps={caps}
              catalogue={catalogue}
              {...shared}
            />
          ))}
        </ul>
      )}

      {otherCompetencies.length > 0 && (
        <section className="card subsection-card" aria-labelledby="cap-other-services">
          <h2 id="cap-other-services">{tc.otherServices}</h2>
          <ul className="plain" aria-label={tc.otherServices}>
            {otherCompetencies.map((c) => (
              <CompetencyItem key={c.service_id} item={c} offered={false} {...shared} />
            ))}
          </ul>
        </section>
      )}

      <OtherQualifications caps={caps} catalogue={catalogue} shown={shownTypes} {...shared} />

      {adding && (
        <AddSpecialisation
          caps={caps}
          catalogue={catalogue}
          busy={busy}
          feedback={feedback}
          onSubmit={async (id) => {
            if (await run('specialisation:new', () => masterApi.requestSpecialisation(id))) setAdding(false)
          }}
          onClose={() => setAdding(false)}
        />
      )}
      {withdrawal && (
        <ConfirmDialog
          title={tc.withdrawTitle}
          text={tc.withdrawText(withdrawal.name)}
          confirmLabel={tc.withdrawConfirm}
          busy={busy === withdrawal.item}
          narrow
          onConfirm={async () => {
            await run(withdrawal.item, withdrawal.call)
            setWithdrawal(null) // the result is shown at the item
          }}
          onCancel={() => setWithdrawal(null)}
        />
      )}
    </section>
  )
}

function ProfileStatus({ caps }: { caps: Capabilities }) {
  if (caps.approval_status === 'rejected') {
    return (
      <div className="notice notice-rejected" role="status">
        <p>{tc.rejectedInfo}</p>
        {caps.rejection_reason && (
          <p>
            {tc.rejectionReason}: {caps.rejection_reason}
          </p>
        )}
      </div>
    )
  }
  return (
    <p className={`notice notice-${caps.approval_status}`} role="status">
      {caps.approval_status === 'approved' ? tc.approvedInfo : tc.pendingInfo}
    </p>
  )
}

function ItemFeedback({ item, feedback }: { item: string; feedback: Feedback | null }) {
  if (feedback?.item !== item) return null
  return (
    <p role={feedback.ok ? 'status' : 'alert'} className={feedback.ok ? 'notice notice-approved' : 'error'}>
      {feedback.message}
    </p>
  )
}

/**
 * The row's latest decision. A re-application (owner decision 2026-11-03) is pending again but keeps the
 * previous decision on the row, so a pending row's decision is labelled as the previous one.
 */
function Decided({ at, reason, pending }: { at: string | null; reason: string | null; pending: boolean }) {
  if (!at) return null
  return (
    <div className="muted">
      {pending ? t.decisionHistory.previous : tc.decided}: {rigaDateTime(at)}
      {reason && ` · ${tc.reason}: ${reason}`}
    </div>
  )
}

/** "+ Pievienot specializāciju": a compact dialog with the catalogue's requestable specialisations. */
function AddSpecialisation({
  caps,
  catalogue,
  busy,
  feedback,
  onSubmit,
  onClose,
}: {
  caps: Capabilities
  catalogue: MasterCatalogue
  busy: string | null
  feedback: Feedback | null
  onSubmit: (id: string) => Promise<void>
  onClose: () => void
}) {
  const [value, setValue] = useState('')
  const id = useId()
  const own = new Set(caps.specialisations.map((s) => s.specialisation_id))
  const requestable = catalogue.specialisations.filter((s) => !own.has(s.id))
  const chosenSpec = requestable.find((s) => s.id === value)
  return (
    <ConfirmDialog
      title={tc.addSpecialisationTitle}
      confirmLabel={tc.request}
      confirmTone="primary"
      confirmDisabled={!value}
      busy={busy === 'specialisation:new'}
      narrow
      onConfirm={() => onSubmit(value)}
      onCancel={onClose}
    >
      <ItemFeedback item="specialisation:new" feedback={feedback} />
      {requestable.length === 0 ? (
        <p className="muted">{tc.noneToRequest}</p>
      ) : (
        <div className="field">
          <label htmlFor={id}>{tc.specialisation}</label>
          <select id={id} value={value} onChange={(e) => setValue(e.target.value)}>
            <option value="">{tc.choose}</option>
            {requestable.map((s) => (
              <option key={s.id} value={s.id}>
                {s.status === 'planned' ? `${s.name} (${t.catalogueStatus.planned.toLowerCase()})` : s.name}
              </option>
            ))}
          </select>
          {chosenSpec?.description && (
            <p className="note-line" aria-live="polite">
              <strong>{tc.specialisationAbout}:</strong> {sentence(chosenSpec.description)}
            </p>
          )}
          <small className="hint">{tc.addSpecialisationHint}</small>
        </div>
      )}
    </ConfirmDialog>
  )
}


// --- specialisation card -----------------------------------------------------------------------------------

function SpecialisationCard({
  application,
  offered,
  caps,
  catalogue,
  ...shared
}: Shared & {
  application: SpecialisationApplication
  offered: MasterCatalogueSpecialisation | undefined
  caps: Capabilities
  catalogue: MasterCatalogue
}) {
  const { readOnly, busy, feedback, run, askWithdraw } = shared
  const key = `specialisation:${application.specialisation_id}`
  const name = application.name
  const competencies = caps.competencies.filter((c) => c.specialisation_id === application.specialisation_id)
  const offeredServices = new Set(offered?.services.map((s) => s.id) ?? [])
  const requirements = requirementsOf(offered)
  const rules = new Map(catalogue.qualification_types.map((q) => [q.id, q]))

  return (
    <li className="card">
      <article aria-labelledby={`${key}-title`} className="stack">
        <header className="card-head">
          <div className="user-head">
            <h2 id={`${key}-title`} className="card-title">
              {name}
            </h2>
            <StatusBadge status={application.status} label={t.specialisationStatus[application.status]} />
          </div>
          <div className="muted">
            {tc.requested}: {rigaDateTime(application.requested_at)}
          </div>
          <Decided
            at={application.decided_at}
            reason={application.decision_reason}
            pending={application.status === 'requested'}
          />
          <ItemFeedback item={key} feedback={feedback} />
          {!readOnly && (application.status === WITHDRAWABLE.specialisation || (REAPPLICABLE.has(application.status) && offered)) && (
            <div className="actions">
              {application.status === WITHDRAWABLE.specialisation && (
                <button
                  type="button"
                  className="button-secondary button-small"
                  aria-label={`${tc.withdraw}: ${name}`}
                  disabled={busy !== null}
                  onClick={() =>
                    askWithdraw({ item: key, name, call: () => masterApi.withdrawSpecialisation(application.specialisation_id) })
                  }
                >
                  {tc.withdraw}
                </button>
              )}
              {REAPPLICABLE.has(application.status) && offered && (
                <button
                  type="button"
                  className="button-small"
                  aria-label={`${tc.requestAgain}: ${name}`}
                  aria-busy={busy === key}
                  disabled={busy !== null}
                  onClick={() => void run(key, () => masterApi.requestSpecialisation(application.specialisation_id))}
                >
                  {busy === key ? tc.saving : tc.requestAgain}
                </button>
              )}
            </div>
          )}
        </header>

        <section className="subsection" aria-label={`${tc.services}: ${name}`}>
          <h3>{tc.services}</h3>
          {competencies.length === 0 ? (
            <p className="muted">{tc.noServicesHere}</p>
          ) : (
            <ul className="plain" aria-label={`${tc.services}: ${name}`}>
              {competencies.map((c) => (
                <CompetencyItem key={c.service_id} item={c} offered={offeredServices.has(c.service_id)} {...shared} />
              ))}
            </ul>
          )}
          {!readOnly &&
            (OPEN_SPECIALISATION.has(application.status) ? (
              <AddService application={application} offered={offered} caps={caps} {...shared} />
            ) : (
              <p className="hint">{tc.servicesAfterRequest}</p>
            ))}
        </section>

        {requirements.length > 0 && (
          <section className="subsection" aria-label={`${tc.documents}: ${name}`}>
            <h3>{tc.documents}</h3>
            <ul className="plain">
              {requirements.map((r) => (
                <QualificationItem
                  key={r.id}
                  id={r.id}
                  name={rules.get(r.id)?.name ?? r.id}
                  rule={rules.get(r.id) ?? null}
                  requiredFor={r.wholeSpecialisation ? tc.requiredForAll : tc.requiredFor(r.services.join(', '))}
                  today={caps.today}
                  submissions={caps.qualifications.filter((s) => s.qualification_id === r.id)}
                  {...shared}
                />
              ))}
            </ul>
          </section>
        )}
      </article>
    </li>
  )
}

/** "+ Pievienot pakalpojumu" inside a specialisation: its declarable services the master has not declared yet. */
function AddService({
  application,
  offered,
  caps,
  busy,
  feedback,
  run,
}: Shared & {
  application: SpecialisationApplication
  offered: MasterCatalogueSpecialisation | undefined
  caps: Capabilities
}) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const id = useId()
  const item = `competency:new:${application.specialisation_id}`
  const own = new Set(caps.competencies.map((c) => c.service_id))
  const options = (offered?.services ?? []).filter((s) => !own.has(s.id))
  const chosen = options.some((o) => o.id === value) ? value : ''

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!chosen) return
    if (await run(item, () => masterApi.declareCompetency(chosen))) {
      setValue('')
      setOpen(false)
    }
  }

  if (options.length === 0) {
    return (
      <>
        <ItemFeedback item={item} feedback={feedback} />
        {caps.competencies.some((c) => c.specialisation_id === application.specialisation_id) && (
          <p className="hint">{tc.allServicesDeclared}</p>
        )}
      </>
    )
  }
  return (
    <>
      <ItemFeedback item={item} feedback={feedback} />
      {!open ? (
        <div className="actions">
          <button
            type="button"
            className="button-ghost"
            aria-label={`${tc.addService}: ${application.name}`}
            onClick={() => setOpen(true)}
          >
            {tc.addService}
          </button>
        </div>
      ) : (
        <form className="entry-form" onSubmit={(e) => void submit(e)} aria-label={`${tc.addService}: ${application.name}`}>
          <label htmlFor={id}>{tc.service}</label>
          <select id={id} value={chosen} onChange={(e) => setValue(e.target.value)}>
            <option value="">{tc.choose}</option>
            {options.map((s) => (
              <option key={s.id} value={s.id}>
                {`${s.w_id} ${s.name}${s.status === 'active' ? '' : ` (${(t.catalogueStatus[s.status] ?? s.status).toLowerCase()})`}`}
              </option>
            ))}
          </select>
          <div className="actions">
            <button type="submit" aria-busy={busy === item} disabled={!chosen || busy !== null}>
              {busy === item ? tc.saving : tc.request}
            </button>
            <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => setOpen(false)}>
              {tc.cancel}
            </button>
          </div>
        </form>
      )}
    </>
  )
}

function Reasons({ label, reasons }: { label: string; reasons: DecisionReason[] }) {
  return (
    <ul aria-label={label} className="reasons">
      {reasons.map((r, i) => (
        <li key={`${r.code}-${i}`}>{decisionReasonText(r)}</li>
      ))}
    </ul>
  )
}

function CompetencyItem({
  item,
  offered,
  readOnly,
  busy,
  feedback,
  run,
  askWithdraw,
}: Shared & { item: Competency; offered: boolean }) {
  const key = `competency:${item.service_id}`
  const label = `${item.w_id} ${item.name}`
  return (
    <li className="item-row">
      <div className="user-head">
        <strong>
          <code>{item.w_id}</code> {item.name}
        </strong>
        <StatusBadge status={item.status} label={t.competencyStatus[item.status]} />
      </div>
      <div className="muted">
        {tc.requested}: {rigaDateTime(item.declared_at)}
      </div>
      <Decided at={item.decided_at} reason={item.decision_reason} pending={item.status === 'declared'} />
      {/* R-MST-12: the master's own screen says why orders for this service do not reach them yet. */}
      {item.eligible ? (
        <p className="ok">{tc.eligible}</p>
      ) : (
        item.reasons.length > 0 && <Reasons label={`${tc.notEligible}: ${item.w_id}`} reasons={item.reasons} />
      )}
      <ItemFeedback item={key} feedback={feedback} />
      {!readOnly && (item.status === WITHDRAWABLE.competency || (REAPPLICABLE.has(item.status) && offered)) && (
        <div className="actions">
          {item.status === WITHDRAWABLE.competency && (
            <button
              type="button"
              className="button-secondary button-small"
              aria-label={`${tc.withdraw}: ${label}`}
              disabled={busy !== null}
              onClick={() => askWithdraw({ item: key, name: label, call: () => masterApi.withdrawCompetency(item.service_id) })}
            >
              {tc.withdraw}
            </button>
          )}
          {REAPPLICABLE.has(item.status) && offered && (
            <button
              type="button"
              className="button-small"
              aria-label={`${tc.requestAgain}: ${label}`}
              aria-busy={busy === key}
              disabled={busy !== null}
              onClick={() => void run(key, () => masterApi.declareCompetency(item.service_id))}
            >
              {busy === key ? tc.saving : tc.requestAgain}
            </button>
          )}
        </div>
      )}
    </li>
  )
}

// --- qualifications ------------------------------------------------------------------------------------------

/**
 * Qualification types no specialisation card shows — active types not required by the master's specialisations,
 * and the history of types no longer configured or active — collapsed, so nothing earlier is lost.
 */
function OtherQualifications({
  caps,
  catalogue,
  shown,
  ...shared
}: Shared & { caps: Capabilities; catalogue: MasterCatalogue; shown: Set<string> }) {
  const types = new Map<string, { name: string; rule: QualificationType | null }>()
  for (const rule of catalogue.qualification_types) {
    if (!shown.has(rule.id)) types.set(rule.id, { name: rule.name, rule })
  }
  for (const s of caps.qualifications) {
    if (!shown.has(s.qualification_id) && !types.has(s.qualification_id)) {
      types.set(s.qualification_id, { name: s.qualification_name, rule: null })
    }
  }
  if (types.size === 0) return null
  return (
    <details className="card subsection-card">
      <summary>{tc.otherQualifications(types.size)}</summary>
      <p className="hint">{tc.otherQualificationsHint}</p>
      <ul className="plain" aria-label={tc.otherQualificationsList}>
        {[...types.entries()].map(([id, type]) => (
          <QualificationItem
            key={id}
            id={id}
            name={type.name}
            rule={type.rule}
            requiredFor={null}
            today={caps.today}
            submissions={caps.qualifications.filter((s) => s.qualification_id === id)}
            {...shared}
          />
        ))}
      </ul>
    </details>
  )
}

function QualificationItem({
  id,
  name,
  rule,
  requiredFor,
  today,
  submissions,
  ...shared
}: Shared & {
  id: string
  name: string
  rule: QualificationType | null
  requiredFor: string | null
  today: string
  submissions: Submission[]
}) {
  const [formOpen, setFormOpen] = useState(false)
  const key = `qualification:${id}`
  // The renewal rule as the backend states it (owner decision "Qualification renewal"): one pending submission at
  // a time, and none while a verified one is still valid. `expired` is computed by the backend.
  const pending = submissions.some((s) => s.status === WITHDRAWABLE.qualification)
  const valid = submissions.find((s) => s.status === 'verified' && !s.expired)
  const canSubmit = !shared.readOnly && rule !== null && !pending && !valid

  return (
    <li className="item-row">
      <div className="user-head">
        <strong>{name}</strong>
      </div>
      {requiredFor && <p className="hint">{requiredFor}</p>}
      {rule?.description && <p>{rule.description}</p>}
      {rule && <Rules rule={rule} />}
      {pending && <p className="notice">{tc.pendingSubmission}</p>}
      {!pending && valid && (
        <p className={valid.expires_soon ? 'notice' : 'ok'}>
          {tc.stillValid(valid.valid_until ? calendarDate(valid.valid_until) : null)}
          {valid.expires_soon && valid.valid_until && ` ${tc.expiresSoon(calendarDate(valid.valid_until))}`}
        </p>
      )}
      {!rule && <p className="muted">{tc.notAccepting}</p>}
      <ItemFeedback item={key} feedback={shared.feedback} />
      {canSubmit && !formOpen && (
        <div className="actions">
          <button
            type="button"
            className="button-secondary"
            aria-label={`${submissions.length ? tc.submitNew : tc.submit}: ${name}`}
            onClick={() => setFormOpen(true)}
          >
            {submissions.length ? tc.submitNew : tc.submit}
          </button>
        </div>
      )}
      {canSubmit && formOpen && rule && (
        <SubmissionForm
          rule={rule}
          today={today}
          busy={shared.busy}
          onCancel={() => setFormOpen(false)}
          onSubmit={async (form) => {
            const saved = await shared.run(
              key,
              () => masterApi.submitQualification({ qualificationId: id, ...form }),
              tc.submittedOk,
            )
            if (saved) setFormOpen(false)
          }}
        />
      )}
      {submissions.length === 0 ? (
        <p className="muted">{tc.noSubmissions}</p>
      ) : (
        // The latest submission (and its decision) is always visible; earlier ones are kept, one click away.
        <ul className="plain history" aria-label={`${tc.history}: ${name}`}>
          <SubmissionItem item={submissions[0]} {...shared} />
          {submissions.length > 1 && (
            <li>
              <details>
                <summary>{tc.olderSubmissions(submissions.length - 1)}</summary>
                <ul className="plain history" aria-label={`${tc.olderSubmissionsList}: ${name}`}>
                  {submissions.slice(1).map((s) => (
                    <SubmissionItem key={s.id} item={s} {...shared} />
                  ))}
                </ul>
              </details>
            </li>
          )}
        </ul>
      )}
    </li>
  )
}

function Rules({ rule }: { rule: QualificationType }) {
  const items = [
    rule.requires_document && t.qualifications.requiresDocument,
    rule.requires_document_number && t.qualifications.requiresDocumentNumber,
    rule.requires_expiry_date && t.qualifications.requiresExpiry,
    rule.max_validity_months !== null && `${t.qualifications.maxValidity}: ${rule.max_validity_months}`,
  ].filter((x): x is string => Boolean(x))
  if (items.length === 0) return null
  return (
    <ul aria-label={`${tc.requirements}: ${rule.name}`} className="plain rules muted">
      {items.map((text) => (
        <li key={text}>{text}</li>
      ))}
    </ul>
  )
}

function SubmissionItem({ item, readOnly, busy, feedback, askWithdraw }: Shared & { item: Submission }) {
  const key = `submission:${item.id}`
  return (
    <li className="submission">
      <div className="user-head">
        <StatusBadge status={item.status} label={t.submissionStatus[item.status]} />
        {item.expired && <StatusBadge tone="danger" label={t.masterCard.expired} />}
        {!item.expired && item.expires_soon && <StatusBadge tone="warning" label={t.masterCard.expiresSoon} />}
      </div>
      <dl className="facts">
        <dt>{tc.documentNumber}</dt>
        <dd>{item.document_number ?? '—'}</dd>
        <dt>{tc.validUntil}</dt>
        <dd>{item.valid_until ? calendarDate(item.valid_until) : tc.noExpiry}</dd>
        <dt>{tc.submitted}</dt>
        <dd>{rigaDateTime(item.submitted_at)}</dd>
      </dl>
      <Decided at={item.decided_at} reason={item.decision_reason} pending={item.status === 'submitted'} />
      <Documents submission={item} fetchFile={(fileId, mode) => masterApi.file(item.id, fileId, mode)} />
      <ItemFeedback item={key} feedback={feedback} />
      {!readOnly && item.status === WITHDRAWABLE.qualification && (
        <div className="actions">
          <button
            type="button"
            className="button-secondary button-small"
            aria-label={`${tc.withdraw}: ${item.qualification_name}`}
            disabled={busy !== null}
            onClick={() =>
              askWithdraw({ item: key, name: item.qualification_name, call: () => masterApi.withdrawQualification(item.id) })
            }
          >
            {tc.withdraw}
          </button>
        </div>
      )}
    </li>
  )
}

function SubmissionForm({
  rule,
  today,
  busy,
  onSubmit,
  onCancel,
}: {
  rule: QualificationType
  today: string
  busy: string | null
  onSubmit: (form: { documentNumber: string; validUntil: string; files: File[] }) => Promise<void>
  onCancel: () => void
}) {
  const [documentNumber, setDocumentNumber] = useState('')
  const [validUntil, setValidUntil] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [problems, setProblems] = useState<string[]>([])
  const id = useId()
  const fileProblemsNow = fileProblems(files)

  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? [])
    event.target.value = '' // the same file can be picked again after removing it
    setFiles((prev) => [...prev, ...picked])
    setProblems([])
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = { documentNumber, validUntil, files }
    const found = [...missingFields(rule, form), ...fileProblems(files)]
    setProblems(found)
    if (found.length === 0) await onSubmit(form)
  }

  const required = (on: boolean) => (on ? ` (${tc.required})` : '')
  return (
    <form className="entry-form" onSubmit={(e) => void submit(e)} noValidate aria-label={`${tc.submit}: ${rule.name}`}>
      <div className="field">
        <label htmlFor={`${id}-number`}>{tc.documentNumber + required(rule.requires_document_number)}</label>
        <input
          id={`${id}-number`}
          value={documentNumber}
          maxLength={100}
          aria-required={rule.requires_document_number}
          onChange={(e) => setDocumentNumber(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-until`}>{tc.validUntil + required(rule.requires_expiry_date)}</label>
        <input
          id={`${id}-until`}
          type="date"
          value={validUntil}
          min={today}
          aria-required={rule.requires_expiry_date}
          aria-describedby={rule.max_validity_months !== null ? `${id}-until-hint` : undefined}
          onChange={(e) => setValidUntil(e.target.value)}
        />
        {rule.max_validity_months !== null && (
          <small id={`${id}-until-hint`} className="hint">
            {tc.maxValidity(rule.max_validity_months)}
          </small>
        )}
      </div>
      <div className="field">
        <label htmlFor={`${id}-files`}>{tc.filesLabel + required(rule.requires_document)}</label>
        <input
          id={`${id}-files`}
          type="file"
          multiple
          accept={ACCEPT}
          aria-describedby={`${id}-files-hint`}
          onChange={addFiles}
        />
        <small id={`${id}-files-hint`} className="hint">
          {tc.filesHint}
        </small>
      </div>
      {files.length > 0 && (
        <ul aria-label={tc.selectedFiles} className="plain">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="document">
              <span>
                {file.name} · {Math.max(1, Math.round(file.size / 1024))} KB
              </span>
              <button
                type="button"
                className="button-secondary"
                aria-label={tc.removeFile(file.name)}
                onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {(problems.length > 0 || fileProblemsNow.length > 0) && (
        <ul role="alert" className="error plain">
          {(problems.length > 0 ? problems : fileProblemsNow).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button type="submit" aria-busy={busy !== null} disabled={busy !== null || fileProblemsNow.length > 0}>
          {busy !== null ? tc.sending : tc.send}
        </button>
        <button type="button" className="button-secondary" onClick={onCancel} disabled={busy !== null}>
          {tc.cancel}
        </button>
      </div>
    </form>
  )
}
