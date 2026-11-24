import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { clientApi } from '../../api/work'
import { ClientNav } from '../../components/ClientNav'
import { SetPasswordCard } from '../../components/SetPasswordCard'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Skeleton } from '../../components/Skeleton'
import { StatusBadge } from '../../components/StatusBadge'
import { rigaDateTime } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { ClientRequest, ProposalMaster } from '../../types/work'
import { duration } from '../../work/format'
import { useAction, useLoad } from '../../work/hooks'
import { Countdown, ErrorLine, Money, PrivatePhoto } from '../../work/parts'
import { PlaceFacts } from '../../work/places'

const tr = t.app.request
const FINAL = ['unserved', 'cancelled']

function MasterCard({ master, onChoose, busy, primary }: { master: ProposalMaster; onChoose: () => void; busy: boolean; primary: boolean }) {
  return (
    <li className={`card stack master-card${primary ? ' primary' : ''}`}>
      <div className="card-head">
        <strong className="card-title">{master.first_name}</strong>
        <span className="muted">{master.rating_avg ? tr.rating(Number(master.rating_avg).toFixed(1), master.rating_count) : tr.noRating}</span>
      </div>
      {master.description && <p>{master.description}</p>}
      <p className="muted">
        {tr.eta(master.eta_minutes)} · {tr.jobs(master.completed_jobs)}
      </p>
      <button type="button" className={primary ? undefined : 'button-secondary'} disabled={busy} aria-busy={busy || undefined} onClick={onChoose}>
        {primary ? tr.confirm : tr.choose}
      </button>
    </li>
  )
}

function Timeline({ request }: { request: ClientRequest }) {
  const order = request.order
  if (!order) return null
  const rows: [string, string | null][] = [
    [tr.tAccepted, order.accepted_at],
    [tr.tEnRoute, order.en_route_at],
    [tr.tArrived, order.arrived_at],
    [tr.tStarted, order.work_started_at],
    [tr.tFinished, order.work_completed_at],
    [tr.tCompleted, order.completed_at],
  ]
  return (
    <section className="card stack" aria-labelledby="rq-timeline">
      <h2 id="rq-timeline">{tr.timeline}</h2>
      <ol className="timeline">
        {rows.map(([label, at]) => (
          <li key={label} className={at ? 'done' : undefined}>
            <span>{label}</span>
            <span className="muted">{at ? rigaDateTime(at) : t.app.none}</span>
          </li>
        ))}
      </ol>
      {order.master_location && (
        <p className="muted">
          {tr.approxLocation}:{' '}
          <a href={`https://www.openstreetmap.org/?mlat=${order.master_location.lat}&mlon=${order.master_location.lon}#map=13/${order.master_location.lat}/${order.master_location.lon}`} target="_blank" rel="noreferrer">
            {order.master_location.lat}, {order.master_location.lon}
          </a>
        </p>
      )}
    </section>
  )
}

/** One request of the client: status, the proposed master (option A: confirm first), order progress, summary. */
export function ClientRequestPage() {
  const { id = '' } = useParams()
  usePageTitle(tr.title)
  const { data: request, setData, error, loading, reload } = useLoad(() => clientApi.get(id), 8000, [id])
  const action = useAction()
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [rating, setRating] = useState(5)

  if (loading && !request) return <Skeleton variant="page" />
  if (!request) {
    return (
      <section>
        <ClientNav />
        <p className="notice">{error ?? tr.notFound}</p>
      </section>
    )
  }

  const order = request.order
  const status = order ? order.status : request.status
  const statusLabel = (order ? t.app.orderStatus[order.status] : null) ?? t.app.requestStatus[request.status]
  const choose = async (candidateId: string) => {
    const result = await action.run(() => clientApi.confirm(request.id, candidateId))
    if (result) setData(result)
    else void reload()
  }
  const cancellable = ['draft', 'matching', 'proposed', 'confirmed'].includes(request.status) && (!order || ['offered', 'accepted', 'scheduled', 'en_route'].includes(order.status))

  return (
    <section>
      <ClientNav />
      <Link to="/client" className="back-link">
        <span aria-hidden="true">←</span> {tr.back}
      </Link>
      <div className="page-head">
        <h1>
          <code>{request.service.w_id}</code> {request.service.name}
        </h1>
        <StatusBadge label={statusLabel} tone={FINAL.includes(status) ? 'danger' : status === 'completed' || status === 'reviewed' ? 'success' : 'info'} />
      </div>
      <ErrorLine message={action.error} />

      {request.status === 'matching' && (
        <p className="notice" role="status">
          {tr.matching} {tr.round(Math.max(1, request.current_round))}
        </p>
      )}

      {request.status === 'proposed' && request.proposal && (
        <section className="stack" aria-labelledby="rq-proposal">
          <div className="page-head">
            <h2 id="rq-proposal">{tr.proposalTitle}</h2>
            <Countdown until={request.proposal.expires_at} label={tr.confirmIn} />
          </div>
          <p className="muted">{tr.round(request.proposal.round)}</p>
          <ul className="plain master-grid">
            {request.proposal.masters.map((m) => (
              <MasterCard key={m.candidate_id} master={m} primary={m.role === 'proposal'} busy={action.busy} onChoose={() => void choose(m.candidate_id)} />
            ))}
          </ul>
          <div className="actions">
            <button
              type="button"
              className="button-ghost"
              disabled={action.busy}
              onClick={async () => {
                const result = await action.run(() => clientApi.reject(request.id))
                if (result) setData(result)
              }}
            >
              {tr.reject}
            </button>
          </div>
        </section>
      )}

      {request.status === 'confirmed' && order?.status === 'offered' && (
        <p className="notice" role="status">
          {tr.waitingMaster}
        </p>
      )}
      {request.status === 'unserved' && <p className="notice notice-rejected">{tr.unserved}</p>}
      {request.status === 'cancelled' && <p className="notice">{tr.cancelledText}</p>}

      {order && order.status !== 'offered' && order.status !== 'cancelled' && (
        <section className="card stack" aria-labelledby="rq-master">
          <h2 id="rq-master">{tr.master}</h2>
          <p>
            <strong>{order.master_name}</strong>
            {order.master_phone && (
              <>
                {' · '}
                {tr.phone}: <a href={`tel:${order.master_phone}`}>{order.master_phone}</a>
              </>
            )}
          </p>
        </section>
      )}

      <Timeline request={request} />

      {order && (order.status === 'completed' || order.status === 'reviewed') && (
        <section className="card stack" aria-labelledby="rq-summary">
          <h2 id="rq-summary">{tr.summary}</h2>
          {order.work_description && <p>{order.work_description}</p>}
          <dl className="summary-list">
            <dt>{tr.workTime}</dt>
            <dd>{order.billable_minutes != null ? duration(order.billable_minutes * 60) : t.app.none}</dd>
            <dt>{tr.labour}</dt>
            <dd>
              <Money value={order.labour_amount_eur} />
            </dd>
            <dt>{tr.materials}</dt>
            <dd>
              <Money value={order.materials_amount_eur} />
            </dd>
          </dl>
          <p className="hint">{tr.payNote}</p>
          {order.status === 'completed' ? (
            <form
              className="inline-form"
              onSubmit={async (e) => {
                e.preventDefault()
                if (await action.run(() => clientApi.review(order.id, rating))) void reload()
              }}
            >
              <label htmlFor="rq-rating">{tr.rate}</label>
              <select id="rq-rating" value={rating} onChange={(e) => setRating(Number(e.target.value))}>
                {[5, 4, 3, 2, 1].map((n) => (
                  <option key={n} value={n}>
                    {tr.rateLabel(n)}
                  </option>
                ))}
              </select>
              <button type="submit" disabled={action.busy}>
                {tr.sendReview}
              </button>
            </form>
          ) : (
            order.review_rating && <p className="ok">{tr.reviewed(order.review_rating)}</p>
          )}
        </section>
      )}

      <section className="card stack" aria-labelledby="rq-details">
        <h2 id="rq-details">{tr.title}</h2>
        <dl className="summary-list">
          <dt>{tr.service}</dt>
          <dd>
            {request.service.category} → {request.service.specialisation}
          </dd>
          <dt>{tr.description}</dt>
          <dd>{request.description}</dd>
          <dt>{tr.address}</dt>
          <dd>
            {request.address}
            {request.flat && ` · ${request.flat}`}
          </dd>
          <PlaceFacts city={request.city} communicationLanguage={request.communication_language} />
          <dt>{tr.when}</dt>
          <dd>
            {request.request_type === 'immediate' || !request.preferred_time_from || !request.preferred_time_to
              ? tr.asap
              : tr.window(rigaDateTime(request.preferred_time_from), rigaDateTime(request.preferred_time_to))}
          </dd>
          <dt>{tr.created}</dt>
          <dd>{rigaDateTime(request.created_at)}</dd>
        </dl>
        {request.photos.length > 0 && (
          <ul className="thumbs" aria-label={tr.photos}>
            {request.photos.map((p, i) => (
              <li key={p.id}>
                <PrivatePhoto load={() => clientApi.photo(request.id, p.id)} alt={`${tr.photos} ${i + 1}`} />
              </li>
            ))}
          </ul>
        )}
        {cancellable && (
          <div className="actions">
            <button type="button" className="button-danger button-small" onClick={() => setConfirmCancel(true)}>
              {tr.cancel}
            </button>
          </div>
        )}
      </section>

      {confirmCancel && (
        <ConfirmDialog
          title={tr.cancel}
          text={tr.cancelConfirm}
          confirmLabel={tr.cancel}
          busy={action.busy}
          narrow
          onCancel={() => setConfirmCancel(false)}
          onConfirm={async () => {
            setConfirmCancel(false)
            const result = await action.run(() => clientApi.cancel(request.id))
            if (result) setData(result)
          }}
        />
      )}
      <SetPasswordCard />
    </section>
  )
}
