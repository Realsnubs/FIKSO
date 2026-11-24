import { Skeleton } from '../../../components/Skeleton'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useCallback, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { adminMastersApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { StatusBadge } from '../../../components/StatusBadge'
import { t } from '../../../i18n/lv'
import type { MasterApprovalStatus } from '../../../types/api'
import type { AdminMasterListItem } from '../../../types/masters'
import { rigaDate } from '../../../i18n/format'
import { usePaged } from './paging'

const tm = t.masters

/** "Meistari": every master with the number of items waiting for a decision (step 4.6.4, ARCHITECTURE §6b). */
export function MastersPage() {
  usePageTitle(tm.title)
  const [params] = useSearchParams()
  const fromUrl = params.get('approval_status')
  const [approval, setApproval] = useState<MasterApprovalStatus | ''>(
    fromUrl === 'pending_approval' || fromUrl === 'approved' || fromUrl === 'rejected' ? fromUrl : '',
  )
  const [pending, setPending] = useState<'' | 'yes' | 'no'>('')
  const fetchPage = useCallback(
    (cursor: string | null) =>
      adminMastersApi.list({
        approvalStatus: approval || undefined,
        hasPending: pending === '' ? undefined : pending === 'yes',
        cursor,
      }),
    [approval, pending],
  )
  const list = usePaged(fetchPage)

  return (
    <section>
      <AdminNav />
      <h1>{tm.title}</h1>
      <div className="filters">
        <label>
          {tm.filterApproval}
          <select
            value={approval}
            onChange={(e) => {
              list.beginLoading()
              setApproval(e.target.value as MasterApprovalStatus | '')
            }}
          >
            <option value="">{t.admin.all}</option>
            <option value="pending_approval">{t.approval.pending_approval}</option>
            <option value="approved">{t.approval.approved}</option>
            <option value="rejected">{t.approval.rejected}</option>
          </select>
        </label>
        <label>
          {tm.filterPending}
          <select
            value={pending}
            onChange={(e) => {
              list.beginLoading()
              setPending(e.target.value as '' | 'yes' | 'no')
            }}
          >
            <option value="">{t.admin.all}</option>
            <option value="yes">{tm.withPending}</option>
            <option value="no">{tm.withoutPending}</option>
          </select>
        </label>
      </div>

      {list.error && (
        <p role="alert" className="error">
          {list.error}{' '}
          <button type="button" className="button-secondary" onClick={list.retry}>
            {t.retry}
          </button>
        </p>
      )}
      {!list.loading && !list.error && list.items.length === 0 && <p className="empty">{tm.empty}</p>}

      <ul className="user-list" aria-label={tm.title}>
        {list.items.map((master) => (
          <MasterCard key={master.id} master={master} />
        ))}
      </ul>

      {list.loading && <Skeleton />}
      {!list.loading && list.hasMore && (
        <button type="button" className="button-secondary" onClick={() => void list.loadMore()}>
          {t.admin.loadMore}
        </button>
      )}
    </section>
  )
}

function MasterCard({ master }: { master: AdminMasterListItem }) {
  const { specialisations, competencies, qualifications } = master.pending
  const waiting = specialisations + competencies + qualifications
  return (
    <li className="card">
      <div className="user-head">
        <Link to={`/admin/masters/${master.id}`}>
          <strong>{master.full_name}</strong>
        </Link>
        <StatusBadge status={master.approval_status} label={t.approval[master.approval_status]} />
        {master.user_status === 'blocked' && <span className="badge badge-blocked">{t.status.blocked}</span>}
      </div>
      <div className="muted">
        {master.email}
        {master.phone && ` · ${master.phone}`} · {t.admin.registered} {rigaDate(master.registered_at)}
        {master.decided_at && ` · ${tm.decided} ${rigaDate(master.decided_at)}`}
      </div>
      <p className={waiting > 0 ? 'notice' : 'muted'}>
        {waiting > 0
          ? `${tm.waiting}: ${tm.specialisations} ${specialisations}, ${tm.competencies} ${competencies}, ${tm.qualifications} ${qualifications}`
          : tm.nothingWaiting}
      </p>
    </li>
  )
}
