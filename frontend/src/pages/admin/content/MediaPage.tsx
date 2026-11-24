import { useState, type FormEvent } from 'react'
import { adminWorkApi } from '../../../api/work'
import { AdminNav } from '../../../components/AdminNav'
import { Skeleton } from '../../../components/Skeleton'
import { StatusBadge } from '../../../components/StatusBadge'
import { rigaDate } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { usePageTitle } from '../../../i18n/usePageTitle'
import type { MediaItem } from '../../../types/work'
import { useAction, useLoad } from '../../../work/hooks'
import { ErrorLine } from '../../../work/parts'

const tm = t.app.admin.media

/** Public catalogue images (OQ-10/11): upload with legal basis and personal-data check; archive or withdraw. */
export function MediaPage() {
  usePageTitle(tm.title)
  const { data, setData, error, loading } = useLoad(() => adminWorkApi.media())
  const action = useAction()
  const [basis, setBasis] = useState<MediaItem['rights_basis']>('own')
  const [formKey, setFormKey] = useState(0)

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    form.set('personal_data_checked', form.get('personal_data_checked') ? 'true' : 'false')
    for (const key of ['rights_reference', 'consent_given_on', 'alt_lv', 'alt_en', 'alt_ru']) if (!form.get(key)) form.delete(key)
    const item = await action.run(() => adminWorkApi.uploadMedia(form))
    if (item) {
      setData([item, ...(data ?? [])])
      setFormKey((k) => k + 1)
    }
  }

  async function change(item: MediaItem, kind: 'archive' | 'withdraw') {
    const reason = window.prompt(t.app.reason)
    if (!reason || reason.trim().length < 3) return
    const updated = await action.run(() => (kind === 'archive' ? adminWorkApi.archiveMedia(item.id, reason) : adminWorkApi.withdrawConsent(item.id, reason)))
    if (updated) setData((data ?? []).map((m) => (m.id === updated.id ? updated : m)))
  }

  return (
    <section>
      <AdminNav />
      <h1>{tm.title}</h1>
      <p className="hint">{tm.legal}</p>
      <ErrorLine message={action.error ?? error} />
      <form key={formKey} className="card stack" onSubmit={upload}>
        <h2>{tm.upload}</h2>
        <div className="field">
          <label htmlFor="md-file">{tm.file}</label>
          <input id="md-file" name="file" type="file" accept="image/jpeg,image/png,image/webp" required />
        </div>
        <div className="field">
          <label htmlFor="md-basis">{tm.basis}</label>
          <select id="md-basis" name="rights_basis" value={basis} onChange={(e) => setBasis(e.target.value as MediaItem['rights_basis'])}>
            {(['own', 'client_consent', 'licence'] as const).map((b) => (
              <option key={b} value={b}>
                {tm.bases[b]}
              </option>
            ))}
          </select>
        </div>
        {basis !== 'own' && (
          <>
            <div className="field">
              <label htmlFor="md-ref">{tm.reference}</label>
              <input id="md-ref" name="rights_reference" maxLength={300} required={basis === 'client_consent'} />
            </div>
            {basis === 'client_consent' && (
              <div className="field">
                <label htmlFor="md-date">{tm.consentDate}</label>
                <input id="md-date" name="consent_given_on" type="date" required />
              </div>
            )}
          </>
        )}
        {(['lv', 'en', 'ru'] as const).map((l) => (
          <div key={l} className="field">
            <label htmlFor={`md-alt-${l}`}>
              {tm.alt} ({l.toUpperCase()})
            </label>
            <input id={`md-alt-${l}`} name={`alt_${l}`} maxLength={200} required={l === 'lv'} />
          </div>
        ))}
        <label className="checkbox">
          <input type="checkbox" name="personal_data_checked" required /> {tm.checked}
        </label>
        <div className="actions">
          <button type="submit" disabled={action.busy} aria-busy={action.busy || undefined}>
            {tm.upload}
          </button>
        </div>
      </form>
      {loading && !data ? (
        <Skeleton variant="cards" />
      ) : data && data.length ? (
        <ul className="media-grid plain">
          {data.map((m) => (
            <li key={m.id} className="card stack">
              {m.status === 'ready' ? <img src={m.urls['560']} alt={m.alt.lv ?? ''} /> : <div className="media-off" aria-hidden="true" />}
              <div className="muted">
                {m.width}×{m.height} · {tm.bases[m.rights_basis]} · {rigaDate(m.created_at)}
              </div>
              {m.rights_reference && <div className="muted">{m.rights_reference}</div>}
              {m.consent_withdrawn_at ? (
                <StatusBadge label={tm.withdrawn} tone="danger" />
              ) : m.status === 'archived' ? (
                <StatusBadge label={tm.archived} tone="neutral" />
              ) : (
                <div className="actions">
                  <button type="button" className="button-secondary button-small" disabled={action.busy} onClick={() => void change(m, 'archive')}>
                    {tm.archive}
                  </button>
                  {m.rights_basis === 'client_consent' && (
                    <button type="button" className="button-danger button-small" disabled={action.busy} onClick={() => void change(m, 'withdraw')}>
                      {tm.withdraw}
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{tm.empty}</p>
      )}
    </section>
  )
}
