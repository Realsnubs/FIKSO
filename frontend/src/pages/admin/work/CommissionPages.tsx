import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { adminWorkApi } from '../../../api/work'
import { AdminNav } from '../../../components/AdminNav'
import { Skeleton } from '../../../components/Skeleton'
import { rigaToday } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { LedgerTable } from '../../master/MasterCommissionPage'
import { useAction, useLoad } from '../../../work/hooks'
import { ErrorLine, Money } from '../../../work/parts'

const ta = t.app.admin.commission
const tc = t.app.commission

export function CommissionListPage() {
  usePageTitle(ta.title)
  const { data, error, loading } = useLoad(() => adminWorkApi.commission(), 60000)
  return (
    <section>
      <AdminNav />
      <h1>{ta.title}</h1>
      <ErrorLine message={error} />
      {loading && !data ? (
        <Skeleton variant="list" />
      ) : data && data.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">{ta.master}</th>
                <th scope="col" className="num">
                  {ta.balance}
                </th>
                <th scope="col" className="num">
                  {ta.limit}
                </th>
                <th scope="col">
                  <span className="sr-only">{ta.open}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.master_id}>
                  <td>
                    {row.name}
                    <div className="muted">{row.email}</div>
                  </td>
                  <td className="num">
                    <Money value={row.balance_eur} />
                    {row.limit_reached && <div className="badge badge-danger">{ta.reached}</div>}
                  </td>
                  <td className="num">
                    <Money value={row.limit_eur} />
                  </td>
                  <td>
                    <Link to={`/admin/commission/${row.master_id}`}>{ta.open}</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{ta.empty}</p>
      )}
    </section>
  )
}

const today = () => rigaToday()

/** One master's ledger: payments (amount, date, method, comment), corrections and the individual limit. */
export function CommissionMasterPage() {
  const { id = '' } = useParams()
  usePageTitle(ta.title)
  const { data, setData, error, loading } = useLoad(() => adminWorkApi.commissionMaster(id), 0, [id])
  const action = useAction()
  const [formKey, setFormKey] = useState(0)
  // One key per submission: a retry or double click of the same form cannot book a second entry; a new one after success.
  const [keys, setKeys] = useState(() => ({ payment: crypto.randomUUID(), adjustment: crypto.randomUUID() }))

  if (loading && !data) return <Skeleton variant="page" />
  if (!data) return <ErrorLine message={error} />

  const submit = (fn: (form: FormData) => Promise<typeof data>) => async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const result = await action.run(() => fn(form))
    if (result) {
      setData(result)
      setFormKey((k) => k + 1)
      setKeys({ payment: crypto.randomUUID(), adjustment: crypto.randomUUID() })
    }
  }
  const text = (form: FormData, key: string) => String(form.get(key) ?? '').trim()

  return (
    <section>
      <AdminNav />
      <Link to="/admin/commission" className="back-link">
        <span aria-hidden="true">←</span> {ta.back}
      </Link>
      <h1>{data.name}</h1>
      <ErrorLine message={action.error} />
      <div className="kpi-grid">
        <div className="kpi kpi-main">
          <span>{tc.balance}</span>
          <strong>
            <Money value={data.balance_eur} />
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
      <div className="grid-2" key={formKey}>
        <form
          className="card stack"
          onSubmit={submit((f) =>
            adminWorkApi.payment(id, {
              amount_eur: Number(text(f, 'amount')).toFixed(2),
              paid_on: text(f, 'paid_on'),
              payment_method: text(f, 'method') as 'cash' | 'bank_transfer',
              reference: text(f, 'reference') || undefined,
              comment: text(f, 'comment') || undefined,
            }, keys.payment),
          )}
        >
          <h2>{ta.payment}</h2>
          <div className="field">
            <label htmlFor="cp-amount">{ta.amount}</label>
            <input id="cp-amount" name="amount" type="number" min="0.01" step="0.01" required />
          </div>
          <div className="field">
            <label htmlFor="cp-date">{ta.date}</label>
            <input id="cp-date" name="paid_on" type="date" max={today()} defaultValue={today()} required />
          </div>
          <div className="field">
            <label htmlFor="cp-method">{ta.method}</label>
            <select id="cp-method" name="method">
              <option value="bank_transfer">{tc.method.bank_transfer}</option>
              <option value="cash">{tc.method.cash}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="cp-ref">{ta.reference}</label>
            <input id="cp-ref" name="reference" maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor="cp-comment">{t.app.comment}</label>
            <input id="cp-comment" name="comment" maxLength={500} />
          </div>
          <button type="submit" disabled={action.busy}>
            {ta.payment}
          </button>
        </form>
        <div className="stack">
          <form className="card stack" onSubmit={submit((f) => adminWorkApi.adjustment(id, Number(text(f, 'amount')).toFixed(2), text(f, 'reason'), keys.adjustment))}>
            <h2>{ta.adjustment}</h2>
            <div className="field">
              <label htmlFor="ca-amount">{ta.amount}</label>
              <input id="ca-amount" name="amount" type="number" step="0.01" required />
            </div>
            <div className="field">
              <label htmlFor="ca-reason">{t.app.reason}</label>
              <input id="ca-reason" name="reason" minLength={3} maxLength={500} required />
            </div>
            <button type="submit" className="button-secondary" disabled={action.busy}>
              {t.app.save}
            </button>
          </form>
          <form className="card stack" onSubmit={submit((f) => adminWorkApi.limit(id, Number(text(f, 'limit')).toFixed(2), text(f, 'reason')))}>
            <h2>{ta.changeLimit}</h2>
            <div className="field">
              <label htmlFor="cl-limit">{ta.newLimit}</label>
              <input id="cl-limit" name="limit" type="number" min="0" step="0.01" defaultValue={data.limit_eur} required />
            </div>
            <div className="field">
              <label htmlFor="cl-reason">{t.app.reason}</label>
              <input id="cl-reason" name="reason" minLength={3} maxLength={500} required />
            </div>
            <button type="submit" className="button-secondary" disabled={action.busy}>
              {ta.changeLimit}
            </button>
          </form>
        </div>
      </div>
      <section className="card stack" aria-labelledby="cm-entries">
        <h2 id="cm-entries">{tc.entries}</h2>
        <LedgerTable entries={data.entries} />
      </section>
    </section>
  )
}
