import { Skeleton } from '../../../components/Skeleton'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useCallback, useState } from 'react'
import { Link } from 'react-router'
import { adminMastersApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { t } from '../../../i18n/lv'
import type { QueueKind, ReviewQueueItem } from '../../../types/masters'
import { calendarDate, rigaDateTime } from '../../../i18n/format'
import { usePaged } from './paging'

const tq = t.reviewQueue

/** Everything waiting for an admin decision across all masters, oldest first (step 4.6.4, ARCHITECTURE §6b). */
export function ReviewQueuePage() {
  usePageTitle(tq.title)
  const [kind, setKind] = useState<QueueKind | ''>('')
  const fetchPage = useCallback(
    (cursor: string | null) => adminMastersApi.reviewQueue({ kind: kind || undefined, cursor }),
    [kind],
  )
  const queue = usePaged(fetchPage)

  return (
    <section>
      <AdminNav />
      <h1>{tq.title}</h1>
      <p className="muted">{tq.intro}</p>
      <div className="filters">
        <label>
          {tq.filterKind}
          <select
            value={kind}
            onChange={(e) => {
              queue.beginLoading()
              setKind(e.target.value as QueueKind | '')
            }}
          >
            <option value="">{t.admin.all}</option>
            <option value="specialisation">{tq.kinds.specialisation}</option>
            <option value="competency">{tq.kinds.competency}</option>
            <option value="qualification">{tq.kinds.qualification}</option>
          </select>
        </label>
      </div>

      {queue.error && (
        <p role="alert" className="error">
          {queue.error}{' '}
          <button type="button" className="button-secondary" onClick={queue.retry}>
            {t.retry}
          </button>
        </p>
      )}
      {!queue.loading && !queue.error && queue.items.length === 0 && <p className="empty">{tq.empty}</p>}

      <ul className="user-list" aria-label={tq.title}>
        {queue.items.map((item) => (
          <QueueEntry key={`${item.kind}:${item.master_id}:${item.item_id}`} item={item} />
        ))}
      </ul>

      {queue.loading && <Skeleton />}
      {!queue.loading && queue.hasMore && (
        <button type="button" className="button-secondary" onClick={() => void queue.loadMore()}>
          {t.admin.loadMore}
        </button>
      )}
    </section>
  )
}

function QueueEntry({ item }: { item: ReviewQueueItem }) {
  return (
    <li className="card">
      <div className="user-head">
        <span className="badge">{tq.kinds[item.kind]}</span>
        <strong>
          {item.w_id && <code>{item.w_id}</code>} {item.name}
        </strong>
      </div>
      <div className="muted">
        {tq.master}:{' '}
        <Link to={`/admin/masters/${item.master_id}`} aria-label={`${tq.openMaster}: ${item.master_name}`}>
          {item.master_name}
        </Link>{' '}
        · {t.approval[item.approval_status]}
        {item.user_status === 'blocked' && ` · ${t.status.blocked}`}
      </div>
      <div className="muted">
        {tq.since} {rigaDateTime(item.since)}
        {item.valid_until && ` · ${tq.validUntil} ${calendarDate(item.valid_until)}`}
      </div>
    </li>
  )
}
