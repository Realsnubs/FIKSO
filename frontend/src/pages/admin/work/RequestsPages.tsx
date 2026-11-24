import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { adminWorkApi } from '../../../api/work'
import { AdminNav } from '../../../components/AdminNav'
import { Skeleton } from '../../../components/Skeleton'
import { StatusBadge } from '../../../components/StatusBadge'
import { rigaDateTime } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useAction, useLoad } from '../../../work/hooks'
import { ErrorLine } from '../../../work/parts'
import { PlaceFacts } from '../../../work/places'
import { cityName, languageName, usePlaces } from '../../../work/placesData'
import { useLanguage } from '../../../i18n/LanguageContext'

const tq = t.app.admin.requests
const FILTERS = ['', 'matching', 'proposed', 'confirmed', 'unserved', 'cancelled']

export function RequestsListPage() {
  usePageTitle(tq.title)
  const [status, setStatus] = useState('')
  const { data, error, loading } = useLoad(() => adminWorkApi.requests(status || undefined), 20000, [status])
  const { language } = useLanguage()
  const places = usePlaces()
  return (
    <section>
      <AdminNav />
      <h1>{tq.title}</h1>
      <div className="chips" role="group" aria-label={tq.title}>
        {FILTERS.map((f) => (
          <button key={f || 'all'} type="button" className={status === f ? 'chip on' : 'chip'} aria-pressed={status === f} onClick={() => setStatus(f)}>
            {f ? t.app.requestStatus[f] : tq.all}
          </button>
        ))}
      </div>
      <ErrorLine message={error} />
      {loading && !data ? (
        <Skeleton variant="list" />
      ) : data && data.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">{t.app.request.created}</th>
                <th scope="col">{t.app.request.service}</th>
                <th scope="col">{t.app.places.city}</th>
                <th scope="col">{t.app.places.communicationLanguage}</th>
                <th scope="col">{tq.source}</th>
                <th scope="col">{tq.round}</th>
                <th scope="col">{tq.status}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/admin/requests/${r.id}`}>{rigaDateTime(r.created_at)}</Link>
                  </td>
                  <td>
                    <code>{r.w_id}</code> {r.service_name}
                  </td>
                  <td>{r.city ? cityName(places.cities.find((c) => c.code === r.city), language) : t.app.places.none}</td>
                  <td>{languageName(r.communication_language, places.languages, language)}</td>
                  <td>{tq.sources[r.source] ?? r.source}</td>
                  <td>{r.round}</td>
                  <td>
                    <StatusBadge label={(r.order_status && t.app.orderStatus[r.order_status]) || t.app.requestStatus[r.status]} tone={r.status === 'unserved' ? 'danger' : 'info'} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{tq.empty}</p>
      )}
    </section>
  )
}

/** Monitoring of one request: rounds with candidate snapshots and exclusion counts, status history. */
export function RequestDetailPage() {
  const { id = '' } = useParams()
  usePageTitle(tq.title)
  const { data, setData, error, loading } = useLoad(() => adminWorkApi.request(id), 15000, [id])
  const action = useAction()
  if (loading && !data) return <Skeleton variant="page" />
  if (!data) return <ErrorLine message={error} />
  const open = !['cancelled', 'unserved'].includes(data.status) && !(data.order && ['in_progress', 'completed', 'reviewed'].includes(data.order.status))
  return (
    <section>
      <AdminNav />
      <Link to="/admin/requests" className="back-link">
        <span aria-hidden="true">←</span> {tq.back}
      </Link>
      <div className="page-head">
        <h1>
          <code>{data.service.w_id}</code> {data.service.name}
        </h1>
        <StatusBadge label={t.app.requestStatus[data.status]} tone="info" />
      </div>
      <ErrorLine message={action.error} />
      <dl className="summary-list card">
        <dt>{t.app.request.description}</dt>
        <dd>{data.description}</dd>
        <dt>{t.app.request.address}</dt>
        <dd>{data.address}</dd>
        <PlaceFacts city={data.city} communicationLanguage={data.communication_language} />
        <dt>{tq.source}</dt>
        <dd>{tq.sources[data.source] ?? data.source}</dd>
        {data.order && (
          <>
            <dt>{t.app.request.master}</dt>
            <dd>
              {data.order.master_name} · {t.app.orderStatus[data.order.status]}
            </dd>
          </>
        )}
      </dl>
      <section className="card stack" aria-labelledby="ar-rounds">
        <h2 id="ar-rounds">{tq.rounds}</h2>
        {data.rounds.map((r) => (
          <div key={`${r.run_no}-${r.attempt}`} className="stack round">
            <strong>
              {tq.round} {r.run_no}
              {r.attempt > 1 && ` (${r.attempt})`} · {r.outcome} · {r.close_reason ?? '…'}
            </strong>
            <span className="muted">
              {rigaDateTime(r.created_at)} · {r.available}/{r.eligible}
              {Object.keys(r.excluded).length > 0 && ` · ${tq.excluded}: ${Object.entries(r.excluded).map(([k, v]) => `${k} ${v}`).join(', ')}`}
            </span>
            {r.candidates.length > 0 && (
              <ul className="plain">
                {r.candidates.map((c) => (
                  <li key={c.rank}>
                    #{c.rank} {c.master} · {c.eta_minutes} min ({c.eta_source}) · {c.distance_km} km · {c.role}
                    {c.chosen && ' ✓'}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>
      <section className="card stack" aria-labelledby="ar-history">
        <h2 id="ar-history">{tq.history}</h2>
        <ol className="timeline">
          {data.history.map((h, i) => (
            <li key={i} className="done">
              <span>
                {h.entity}: {h.from ?? '∅'} → {h.to}
                {h.reason && <span className="muted"> · {h.reason}</span>}
              </span>
              <span className="muted">{rigaDateTime(h.at)}</span>
            </li>
          ))}
        </ol>
      </section>
      {open && (
        <div className="actions">
          <button
            type="button"
            className="button-danger"
            disabled={action.busy}
            onClick={async () => {
              const reason = window.prompt(t.app.reason)
              if (!reason || reason.trim().length < 3) return
              const result = await action.run(() => adminWorkApi.cancelRequest(id, reason.trim()))
              if (result) setData(result)
            }}
          >
            {tq.cancel}
          </button>
        </div>
      )}
    </section>
  )
}
