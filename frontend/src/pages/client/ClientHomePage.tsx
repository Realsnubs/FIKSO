import { Link } from 'react-router'
import { clientApi } from '../../api/work'
import { ClientNav } from '../../components/ClientNav'
import { SetPasswordCard } from '../../components/SetPasswordCard'
import { Skeleton } from '../../components/Skeleton'
import { StatusBadge } from '../../components/StatusBadge'
import { availableSpecialisations, usePublicCatalogue } from '../../catalogue/publicCatalogue'
import { rigaDateTime } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import { useLoad } from '../../work/hooks'
import { ErrorLine } from '../../work/parts'
import { SpecialisationCard } from './parts'
import { NotificationsPanel } from '../../work/Notifications'

const TONE: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'neutral'> = {
  proposed: 'warning',
  confirmed: 'info',
  matching: 'info',
  unserved: 'danger',
  cancelled: 'neutral',
  completed: 'success',
  reviewed: 'success',
}

/** "Mani pieteikumi": the client's own requests from the API, newest first. */
export function ClientHomePage() {
  usePageTitle(t.client.title)
  const { catalogue } = usePublicCatalogue()
  const { data, error, loading } = useLoad(() => clientApi.list(), 20000)
  const some = (catalogue?.categories ?? [])
    .flatMap((category) => availableSpecialisations(category).map((spec) => ({ spec, category })))
    .slice(0, 3)
  return (
    <section>
      <ClientNav />
      <div className="page-head">
        <h1>{t.client.title}</h1>
        <Link to="/pakalpojumi" className="link-button">
          {t.client.newRequest}
        </Link>
      </div>
      <ErrorLine message={error} />
      <NotificationsPanel />
      <SetPasswordCard />
      {loading && !data ? (
        <Skeleton variant="list" />
      ) : data && data.length > 0 ? (
        <ul className="plain stack" aria-label={t.client.title}>
          {data.map((r) => {
            const status = r.order_status && !['declined', 'expired'].includes(r.order_status) ? r.order_status : r.status
            const label = t.app.orderStatus[status] ?? t.app.requestStatus[status] ?? status
            return (
              <li key={r.id} className="card item-row">
                <div>
                  <strong>
                    <code>{r.w_id}</code> {r.service_name}
                  </strong>
                  <div className="muted">{rigaDateTime(r.created_at)}</div>
                </div>
                <StatusBadge label={label} tone={TONE[status] ?? 'info'} />
                <Link to={`/client/pieteikumi/${r.id}`} className="link-button button-small">
                  {t.app.clientList.open}
                </Link>
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="card stack">
          <p className="empty-title">{t.client.empty}</p>
          <p>{t.client.emptyHint}</p>
        </div>
      )}
      {some.length > 0 && (
        <section className="section-gap" aria-labelledby="ch-services">
          <h2 id="ch-services">{t.client.orderable}</h2>
          <ul className="svc-grid">
            {some.map(({ spec, category }) => (
              <SpecialisationCard key={spec.id} spec={spec} category={category} />
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}
