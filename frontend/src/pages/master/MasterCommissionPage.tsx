import { workApi } from '../../api/work'
import { MasterNav } from '../../components/MasterNav'
import { Skeleton } from '../../components/Skeleton'
import { rigaDate, rigaDateTime } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { LedgerEntry } from '../../types/work'
import { useLoad } from '../../work/hooks'
import { ErrorLine, Money } from '../../work/parts'

const tc = t.app.commission

export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  if (entries.length === 0) return <p className="muted">{tc.empty}</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">{tc.date}</th>
            <th scope="col">{tc.entries}</th>
            <th scope="col" className="num">
              {tc.amount}
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td>{e.paid_on ? rigaDate(e.paid_on) : rigaDateTime(e.created_at)}</td>
              <td>
                {tc.type[e.type]}
                {e.payment_method && ` · ${tc.method[e.payment_method]}`}
                {e.base_labour_eur && (
                  <span className="muted">
                    {' '}
                    (<Money value={e.base_labour_eur} />)
                  </span>
                )}
                {e.comment && <div className="muted">{e.comment}</div>}
              </td>
              <td className="num">
                <Money value={e.amount_eur} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The master's commission balance (balance model: no per-order paid status, payments not allocated). */
export function MasterCommissionPage() {
  usePageTitle(tc.title)
  const { data, error, loading } = useLoad(() => workApi.commission(), 60000)
  if (loading && !data) return <Skeleton variant="page" />
  return (
    <section>
      <MasterNav />
      <h1>{tc.title}</h1>
      <ErrorLine message={error} />
      {data && (
        <>
          <div className="kpi-grid">
            <div className="kpi kpi-main">
              <span>{tc.due}</span>
              <strong>
                <Money value={data.amount_due_eur} />
              </strong>
            </div>
            <div className="kpi">
              <span>{tc.charged}</span>
              <strong>
                <Money value={data.charged_total_eur} />
              </strong>
            </div>
            <div className="kpi">
              <span>{tc.paid}</span>
              <strong>
                <Money value={data.paid_total_eur} />
              </strong>
            </div>
            <div className="kpi">
              <span>{tc.limit}</span>
              <strong>
                <Money value={data.limit_eur} />
              </strong>
              {data.limit_reached && <span className="badge badge-danger">{tc.limitReached}</span>}
            </div>
          </div>
          {data.limit_reached && <p className="notice notice-rejected">{t.app.work.limitReached}</p>}
          <p className="hint">{tc.howToPay}</p>
          <section className="card stack" aria-labelledby="mc-entries">
            <h2 id="mc-entries">{tc.entries}</h2>
            <LedgerTable entries={data.entries} />
          </section>
        </>
      )}
    </section>
  )
}
