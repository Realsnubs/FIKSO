import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { masterApi } from '../../api/endpoints'
import { MasterNav } from '../../components/MasterNav'
import { Skeleton } from '../../components/Skeleton'
import { calendarDate } from '../../i18n/format'
import { errorMessage, t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { Capabilities, Submission } from '../../types/capabilities'

const th = t.masterHome

interface Todo {
  key: string
  text: string
  /** Something the master can act on (as opposed to waiting for the administrator). */
  action: boolean
}

/** The latest submission per qualification type (the API lists them newest first per type). */
function latestPerType(submissions: Submission[]): Submission[] {
  const seen = new Set<string>()
  return submissions.filter((s) => (seen.has(s.qualification_id) ? false : (seen.add(s.qualification_id), true)))
}

/** Everything shown here is counted from GET /master/capabilities; nothing is estimated. */
function overview(caps: Capabilities) {
  const latest = latestPerType(caps.qualifications)
  const waiting =
    caps.specialisations.filter((s) => s.status === 'requested').length +
    caps.competencies.filter((c) => c.status === 'declared').length +
    caps.qualifications.filter((q) => q.status === 'submitted').length
  const todos: Todo[] = []
  for (const q of latest) {
    if (q.status === 'verified' && q.expired && q.valid_until) {
      todos.push({ key: `exp-${q.id}`, text: th.expired(q.qualification_name, calendarDate(q.valid_until)), action: true })
    } else if (q.status === 'verified' && q.expires_soon && q.valid_until) {
      todos.push({ key: `soon-${q.id}`, text: th.expiresSoon(q.qualification_name, calendarDate(q.valid_until)), action: true })
    } else if (q.status === 'rejected') {
      todos.push({ key: `rq-${q.id}`, text: th.rejectedQualification(q.qualification_name), action: true })
    }
  }
  for (const s of caps.specialisations.filter((x) => x.status === 'rejected')) {
    todos.push({ key: `rs-${s.specialisation_id}`, text: th.rejected(s.name), action: true })
  }
  for (const c of caps.competencies.filter((x) => x.status === 'rejected')) {
    todos.push({ key: `rc-${c.service_id}`, text: th.rejected(`${c.w_id} ${c.name}`), action: true })
  }
  if (waiting > 0) todos.push({ key: 'waiting', text: th.waitingItems(waiting), action: false })
  return {
    approved: caps.specialisations.filter((s) => s.status === 'approved').length,
    orderable: caps.competencies.filter((c) => c.eligible).length,
    waiting,
    documents: latest.filter((q) => q.status === 'verified' && (q.expired || q.expires_soon)).length,
    todos,
  }
}

/** The master's start page: profile status, counts and what to do next (R-MST-12, Q-29). */
export function MasterHomePage() {
  usePageTitle(t.master.title)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    masterApi.capabilities().then(
      (found) => !cancelled && (setCaps(found), setError(null)),
      (err: unknown) => !cancelled && setError(errorMessage(err)),
    )
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const view = caps ? overview(caps) : null
  const status = caps?.approval_status
  const info = status === 'approved' ? t.master.approvedInfo : status === 'rejected' ? t.master.rejectedInfo : t.master.pendingInfo

  return (
    <section>
      <MasterNav />
      <h1>{t.master.title}</h1>
      {error && (
        <p role="alert" className="error">
          {error}{' '}
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              setError(null)
              setReloadKey((k) => k + 1)
            }}
          >
            {t.retry}
          </button>
        </p>
      )}
      {!caps && !error && <Skeleton variant="cards" />}
      {caps && view && (
        <>
          {/* Fresh from the API (the login data may be older). */}
          <p className={`notice notice-${caps.approval_status}`} role="status">
            {info}
          </p>
          <div className="stat-grid" aria-label={th.overview} role="group">
            <Stat value={view.approved} label={th.approvedSpecs} />
            <Stat value={view.orderable} label={th.orderableServices} />
            <Stat value={view.waiting} label={th.waiting} attention={view.waiting > 0} />
            <Stat value={view.documents} label={th.documents} attention={view.documents > 0} />
          </div>
          <section className="card" aria-labelledby="mh-next">
            <h2 id="mh-next">{th.nextTitle}</h2>
            {caps.specialisations.length === 0 ? (
              <p>{th.startFirst}</p>
            ) : view.todos.length === 0 ? (
              <p className="muted">{th.nothingToDo}</p>
            ) : (
              <ul className="plain" aria-label={th.nextTitle}>
                {view.todos.map((todo) => (
                  <li key={todo.key} className="queue-row">
                    <span>{todo.text}</span>
                    {todo.action && <Link to="/master/capabilities">{th.open}</Link>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <Link to="/master/capabilities" className="nav-card">
            <strong>
              {t.capabilities.open} <span aria-hidden="true">→</span>
            </strong>
            <span className="muted">{t.capabilities.openHint}</span>
          </Link>
        </>
      )}
    </section>
  )
}

function Stat({ value, label, attention = false }: { value: number; label: string; attention?: boolean }) {
  return (
    <div className="stat">
      <span className={attention ? 'num attn' : 'num'}>{value}</span>
      <span className="lbl">{label}</span>
    </div>
  )
}
