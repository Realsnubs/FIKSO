import { notificationsApi } from '../api/work'
import { rigaDateTime } from '../i18n/format'
import { t } from '../i18n/lv'
import { useLoad } from './hooks'

/** In-app notifications of the signed-in user (unread first by time); marking read is explicit. */
export function NotificationsPanel() {
  const { data, setData } = useLoad(() => notificationsApi.list(), 30000)
  const unread = (data ?? []).filter((n) => !n.read)
  if (!data || unread.length === 0) return null
  return (
    <section className="card stack notifications" aria-labelledby="nt-title" aria-live="polite">
      <div className="card-head">
        <h2 id="nt-title">{t.app.notifications.title}</h2>
        <button
          type="button"
          className="button-ghost button-small"
          onClick={async () => {
            await notificationsApi.read().catch(() => undefined)
            setData(data.map((n) => ({ ...n, read: true })))
          }}
        >
          {t.app.notifications.markRead}
        </button>
      </div>
      <ul className="plain stack">
        {unread.slice(0, 5).map((n) => (
          <li key={n.id} className="item-row">
            <span>{t.app.notifications.types[n.type] ?? n.type}</span>
            <span className="muted">{rigaDateTime(n.created_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
