import { Skeleton } from '../../components/Skeleton'
import { usePageTitle } from '../../i18n/usePageTitle'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { adminApi, type UserFilters } from '../../api/endpoints'
import { useAuth } from '../../auth/context'
import { AdminNav } from '../../components/AdminNav'
import { rigaDate } from '../../i18n/format'
import { errorMessage, t } from '../../i18n/lv'
import type { AdminUser, Role, UserStatus } from '../../types/api'


export function AdminUsersPage() {
  usePageTitle(t.admin.title)
  const { user: me } = useAuth()
  const [role, setRole] = useState<Role | ''>('')
  const [status, setStatus] = useState<UserStatus | ''>('')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [blockingId, setBlockingId] = useState<string | null>(null)

  const [reloadKey, setReloadKey] = useState(0)

  const fetchPage = useCallback(
    (from: UserFilters['cursor']) =>
      adminApi.listUsers({ role: role || undefined, status: status || undefined, cursor: from }),
    [role, status],
  )

  // First page: refetched when filters change or on retry. Loading is set by the handlers that trigger it.
  useEffect(() => {
    let cancelled = false
    fetchPage(null)
      .then((page) => {
        if (cancelled) return
        setUsers(page.items)
        setCursor(page.next_cursor)
        setError(null)
      })
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [fetchPage, reloadKey])

  function reload() {
    setLoading(true)
    setError(null)
    setReloadKey((k) => k + 1)
  }

  async function loadMore() {
    setLoading(true)
    try {
      const page = await fetchPage(cursor)
      setUsers((prev) => [...prev, ...page.items])
      setCursor(page.next_cursor)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function replaceUser(updated: AdminUser) {
    setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
  }

  async function handleBlock(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault()
    const reason = String(new FormData(event.currentTarget).get('reason'))
    try {
      replaceUser(await adminApi.blockUser(id, reason))
      setBlockingId(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleUnblock(id: string) {
    try {
      replaceUser(await adminApi.unblockUser(id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <section>
      <AdminNav />
      <h1>{t.admin.title}</h1>
      <div className="filters">
        <label>
          {t.admin.filterRole}
          <select value={role} onChange={(e) => {
              setLoading(true)
              setRole(e.target.value as Role | '')
            }}>
            <option value="">{t.admin.all}</option>
            <option value="client">{t.roles.client}</option>
            <option value="master">{t.roles.master}</option>
            <option value="admin">{t.roles.admin}</option>
          </select>
        </label>
        <label>
          {t.admin.filterStatus}
          <select value={status} onChange={(e) => {
              setLoading(true)
              setStatus(e.target.value as UserStatus | '')
            }}>
            <option value="">{t.admin.all}</option>
            <option value="active">{t.status.active}</option>
            <option value="blocked">{t.status.blocked}</option>
          </select>
        </label>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}{' '}
          <button type="button" className="button-secondary" onClick={reload}>
            {t.retry}
          </button>
        </p>
      )}
      {!loading && !error && users.length === 0 && <p className="empty">{t.admin.empty}</p>}

      <ul className="user-list">
        {users.map((u) => (
          <li key={u.id} className="card">
            <div className="user-head">
              <strong>{u.full_name}</strong>
              <span className={`badge badge-${u.status}`}>{t.status[u.status]}</span>
            </div>
            <div className="muted">
              {t.roles[u.role]}
              {u.master_approval_status && ` · ${t.approval[u.master_approval_status]}`} · {u.email} ·{' '}
              {t.admin.registered} {rigaDate(u.created_at)}
            </div>
            {u.blocked_reason && <div className="muted">{u.blocked_reason}</div>}
            {u.id !== me?.id &&
              (u.status === 'blocked' ? (
                <button type="button" className="button-secondary" onClick={() => void handleUnblock(u.id)}>
                  {t.admin.unblock}
                </button>
              ) : blockingId === u.id ? (
                <form className="inline-form" onSubmit={(e) => void handleBlock(e, u.id)}>
                  <label>
                    {t.admin.blockReason}
                    <input name="reason" required minLength={3} maxLength={500} autoFocus />
                  </label>
                  <button type="submit" className="button-danger">
                    {t.admin.confirmBlock}
                  </button>
                  <button type="button" className="button-secondary" onClick={() => setBlockingId(null)}>
                    {t.admin.cancel}
                  </button>
                </form>
              ) : (
                <button type="button" className="button-secondary" onClick={() => setBlockingId(u.id)}>
                  {t.admin.block}
                </button>
              ))}
          </li>
        ))}
      </ul>

      {loading && <Skeleton />}
      {!loading && cursor && (
        <button type="button" className="button-secondary" onClick={() => void loadMore()}>
          {t.admin.loadMore}
        </button>
      )}
    </section>
  )
}
