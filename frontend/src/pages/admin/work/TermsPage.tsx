import { useState, type FormEvent } from 'react'
import { adminWorkApi } from '../../../api/work'
import { AdminNav } from '../../../components/AdminNav'
import { Skeleton } from '../../../components/Skeleton'
import { StatusBadge } from '../../../components/StatusBadge'
import { rigaDateTime } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useAction, useLoad } from '../../../work/hooks'
import { ErrorLine, Money } from '../../../work/parts'

const tt = t.app.admin.terms

/** Commercial terms with history (C1), the owner-decided timers and the open working assumptions (Q-D2-1). */
export function TermsPage() {
  usePageTitle(tt.title)
  const terms = useLoad(() => adminWorkApi.terms())
  const settings = useLoad(() => adminWorkApi.settings())
  const action = useAction()
  const current = terms.data?.[0]
  const [form, setForm] = useState<Record<string, string> | null>(null)
  const values = form ?? {
    rate: current?.hourly_rate_eur ?? '40.00',
    minimum: current?.minimum_order_eur ?? '40.00',
    lv: current?.materials_note.lv ?? '',
    en: current?.materials_note.en ?? '',
    ru: current?.materials_note.ru ?? '',
    reason: '',
  }
  const set = (key: string, value: string) => setForm({ ...values, [key]: value })

  async function save(event: FormEvent) {
    event.preventDefault()
    const created = await action.run(() =>
      adminWorkApi.createTerms({
        hourly_rate_eur: Number(values.rate).toFixed(2),
        minimum_order_eur: Number(values.minimum).toFixed(2),
        materials_note: { lv: values.lv, en: values.en || undefined, ru: values.ru || undefined },
        reason: values.reason,
      }),
    )
    if (created) {
      setForm(null)
      void terms.reload()
    }
  }

  const s = settings.data as
    | {
        client_confirmation_minutes: { immediate: number; reserved: number }
        master_response_minutes: { immediate: number; reserved: number }
        immediate_job_minutes: number
        order_buffer_minutes: number
        billable_time: { rounding: string; step_minutes: number }
        policy_confirmation: Record<string, boolean>
        unconfirmed_policies: string[]
        billable_options: Record<string, { rounding: string; step_minutes: number; note: string }>
      }
    | null

  return (
    <section>
      <AdminNav />
      <h1>{tt.title}</h1>
      <ErrorLine message={action.error ?? terms.error} />
      {s && s.unconfirmed_policies.length > 0 && (
        <p className="notice notice-rejected" role="status">
          {tt.unconfirmedBanner}
          {s.unconfirmed_policies.map((p) => tt.policies[p] ?? p).join(', ')}
        </p>
      )}
      {terms.loading && !terms.data ? (
        <Skeleton variant="page" />
      ) : (
        <form className="card stack" onSubmit={save}>
          <p className="hint">{tt.note}</p>
          <div className="field">
            <label htmlFor="tr-rate">{tt.rate}</label>
            <input id="tr-rate" type="number" min="1" step="0.01" value={values.rate} onChange={(e) => set('rate', e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="tr-min">{tt.minimum}</label>
            <input id="tr-min" type="number" min="0" step="0.01" value={values.minimum} onChange={(e) => set('minimum', e.target.value)} required />
          </div>
          {(['lv', 'en', 'ru'] as const).map((l) => (
            <div key={l} className="field">
              <label htmlFor={`tr-m-${l}`}>
                {tt.materials} ({l.toUpperCase()})
              </label>
              <input id={`tr-m-${l}`} maxLength={600} value={values[l]} onChange={(e) => set(l, e.target.value)} required={l === 'lv'} />
            </div>
          ))}
          <div className="field">
            <label htmlFor="tr-reason">{tt.reason}</label>
            <input id="tr-reason" minLength={3} maxLength={500} value={values.reason} onChange={(e) => set('reason', e.target.value)} required />
          </div>
          <div className="actions">
            <button type="submit" disabled={action.busy || !form}>
              {tt.create}
            </button>
          </div>
        </form>
      )}
      <section className="card stack" aria-labelledby="tr-history">
        <h2 id="tr-history">{tt.history}</h2>
        <ul className="plain stack">
          {(terms.data ?? []).map((row, i) => (
            <li key={row.id} className="item-row">
              <span>
                <Money value={row.hourly_rate_eur} />
                /h · min <Money value={row.minimum_order_eur} /> · {rigaDateTime(row.effective_from)}
                {row.reason && <span className="muted"> · {row.reason}</span>}
              </span>
              {i === 0 && <StatusBadge label={tt.current} tone="success" />}
            </li>
          ))}
        </ul>
      </section>
      {s && (
        <section className="card stack" aria-labelledby="tr-timers">
          <h2 id="tr-timers">{tt.timers}</h2>
          <dl className="summary-list">
            <dt>{tt.clientTimer}</dt>
            <dd>{tt.timerValue(s.client_confirmation_minutes.immediate, s.client_confirmation_minutes.reserved)}</dd>
            <dt>{tt.masterTimer}</dt>
            <dd>{tt.timerValue(s.master_response_minutes.immediate, s.master_response_minutes.reserved)}</dd>
          </dl>
          <h3>{tt.billable}</h3>
          <form
            className="inline-form"
            onSubmit={async (e) => {
              e.preventDefault()
              const data = new FormData(e.currentTarget)
              const updated = await action.run(() =>
                adminWorkApi.putBillableRule(String(data.get('rounding')), Number(data.get('step')), String(data.get('reason'))),
              )
              if (updated) settings.setData(updated)
            }}
          >
            <label>
              {tt.rounding}
              <select name="rounding" defaultValue={s.billable_time.rounding}>
                {['none', 'up', 'nearest', 'down'].map((r) => (
                  <option key={r} value={r}>
                    {tt.roundings[r]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {tt.step}
              <input name="step" type="number" min={1} max={60} defaultValue={s.billable_time.step_minutes} required />
            </label>
            <input name="reason" aria-label={tt.reason} placeholder={tt.reason} minLength={3} required />
            <button type="submit" className="button-secondary button-small" disabled={action.busy}>
              {tt.saveRule}
            </button>
          </form>
          <p className="hint">
            {tt.options}: {Object.entries(s.billable_options).map(([k, o]) => `${k} — ${tt.roundings[o.rounding]} ${o.step_minutes} min`).join(' · ')}
          </p>
          <ul className="plain stack">
            {(['billable_time', 'immediate_job_minutes', 'order_buffer_minutes'] as const).map((policy) => {
              const approved = Boolean(s.policy_confirmation[policy])
              return (
                <li key={policy} className="item-row">
                  <span>
                    {tt.policies[policy]} · <StatusBadge label={approved ? tt.approved : tt.unapproved} tone={approved ? 'success' : 'warning'} />
                  </span>
                  <button
                    type="button"
                    className="button-ghost button-small"
                    disabled={action.busy}
                    onClick={async () => {
                      const reason = window.prompt(tt.reason)
                      if (!reason || reason.trim().length < 3) return
                      const updated = await action.run(() => adminWorkApi.confirmPolicy(policy, !approved, reason.trim()))
                      if (updated) settings.setData(updated)
                    }}
                  >
                    {approved ? tt.withdrawApproval : tt.approve}
                  </button>
                </li>
              )
            })}
          </ul>
          <h3>{tt.settings}</h3>
          {(
            [
              ['immediate_job_minutes', tt.jobMinutes, s.immediate_job_minutes],
              ['order_buffer_minutes', tt.bufferMinutes, s.order_buffer_minutes],
            ] as const
          ).map(([key, label, value]) => (
            <form
              key={key}
              className="inline-form"
              onSubmit={async (e) => {
                e.preventDefault()
                const data = new FormData(e.currentTarget)
                const updated = await action.run(() => adminWorkApi.putSetting(key, Number(data.get('value')), String(data.get('reason'))))
                if (updated) settings.setData(updated)
              }}
            >
              <label htmlFor={`st-${key}`}>{label}</label>
              <input id={`st-${key}`} name="value" type="number" defaultValue={value} min={0} max={720} required />
              <input name="reason" aria-label={tt.reason} placeholder={tt.reason} minLength={3} required />
              <button type="submit" className="button-secondary button-small" disabled={action.busy}>
                {t.app.save}
              </button>
            </form>
          ))}
        </section>
      )}
    </section>
  )
}
