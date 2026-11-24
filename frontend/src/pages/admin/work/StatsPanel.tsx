import { adminWorkApi } from '../../../api/work'
import { rigaDateTime } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { useLoad } from '../../../work/hooks'
import { ErrorLine, Money } from '../../../work/parts'

const ts = t.app.admin.stats

/** Exact platform figures for the last 30 days from GET /admin/stats/overview (nothing estimated). */
export function StatsPanel() {
  const { data, error } = useLoad(() => adminWorkApi.stats(30), 60000)
  if (error) return <ErrorLine message={error} />
  if (!data) return null
  const n = (map: Record<string, number>, key: string) => map[key] ?? 0
  const totalRequests = Object.values(data.requests.by_status).reduce((a, b) => a + b, 0)
  const items: [string, string | number | React.ReactNode][] = [
    [ts.views, n(data.public, 'catalogue_view')],
    [ts.selected, n(data.public, 'service_selected')],
    [ts.requests, totalRequests],
    [ts.fromWeb, n(data.requests.by_source, 'website_deeplink')],
    [ts.unserved, n(data.requests.by_status, 'unserved')],
    [ts.accepted, n(data.matching.round_endings, 'master_accepted')],
    [ts.declined, n(data.matching.round_endings, 'master_declined')],
    [ts.expired, n(data.matching.round_endings, 'master_expired')],
    [ts.completed, n(data.orders, 'completed') + n(data.orders, 'reviewed')],
    [ts.charged, <Money key="c" value={data.commission.charged_eur} />],
    [ts.paidIn, <Money key="p" value={data.commission.paid_eur} />],
    [ts.outstanding, <Money key="o" value={data.commission.outstanding_eur} />],
  ]
  return (
    <section className="card section-gap" aria-labelledby="ad-stats">
      <h2 id="ad-stats">{ts.title}</h2>
      <dl className="kpi-grid">
        {items.map(([label, value]) => (
          <div key={label} className="kpi">
            <dt>{label}</dt>
            <dd>
              <strong>{value}</strong>
            </dd>
          </div>
        ))}
      </dl>
      <p className="muted">
        {ts.worker}: {data.worker.last_finished_at ? ts.workerOk(rigaDateTime(data.worker.last_finished_at)) : ts.workerNever}
        {data.worker.stuck_runs > 0 && ` · ${ts.stuck(data.worker.stuck_runs)}`}
      </p>
    </section>
  )
}
