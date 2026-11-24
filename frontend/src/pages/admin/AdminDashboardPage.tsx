import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { adminMastersApi, catalogueApi } from '../../api/endpoints'
import { AdminNav } from '../../components/AdminNav'
import { Skeleton } from '../../components/Skeleton'
import { rigaDate } from '../../i18n/format'
import { errorMessage, t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { Page } from '../../types/api'
import type { CatalogueTree } from '../../types/catalogue'
import type { AdminMasterListItem, ReviewQueueItem } from '../../types/masters'
import { StatsPanel } from './work/StatsPanel'

const ta = t.adminHome
const SHOWN = 5

/** One request's state: the data, or the Latvian/English/Russian error, or still loading. */
interface Load<T> {
  data: T | null
  error: string | null
}

function useLoad<T>(fetcher: () => Promise<T>): Load<T> {
  const [state, setState] = useState<Load<T>>({ data: null, error: null })
  useEffect(() => {
    let cancelled = false
    fetcher().then(
      (data) => !cancelled && setState({ data, error: null }),
      (err: unknown) => !cancelled && setState({ data: null, error: errorMessage(err) }),
    )
    return () => {
      cancelled = true
    }
    // The fetchers are stable module-level calls; load once per visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return state
}

/** A count from one page of a list: exact, or "25+" when the API says there are more (no invented totals). */
function pageCount(page: Page<unknown>): string {
  return page.next_cursor ? ta.moreThan(page.items.length) : String(page.items.length)
}

/** Catalogue figures straight from the admin tree. */
function catalogueFigures(tree: CatalogueTree) {
  const services = tree.categories.flatMap((c) => c.specialisations.flatMap((s) => s.services))
  const live = services.filter((s) => s.status !== 'archived' && s.status !== 'rejected')
  return {
    total: live.length,
    orderable: services.filter((s) => s.orderable).length,
    drafts: services.filter((s) => s.status === 'draft').length,
    flagged: live.filter((s) => s.review_note).length,
    hold: services.filter((s) => s.status === 'hold').length,
  }
}

/** The administrator's start page: what waits for a decision and the state of the catalogue (stage A). */
export function AdminDashboardPage() {
  usePageTitle(ta.title)
  const queue = useLoad(() => adminMastersApi.reviewQueue({}))
  const profiles = useLoad(() => adminMastersApi.list({ approvalStatus: 'pending_approval' }))
  const tree = useLoad(() => catalogueApi.tree())
  const figures = tree.data ? catalogueFigures(tree.data) : null

  return (
    <section>
      <AdminNav />
      <h1>{ta.title}</h1>
      <div className="stat-grid" role="group" aria-label={ta.title}>
        <Stat to="/admin/review-queue" value={queue.data && pageCount(queue.data)} label={ta.waiting} go={ta.openQueue} attention />
        <Stat
          to="/admin/masters?approval_status=pending_approval"
          value={profiles.data && pageCount(profiles.data)}
          label={ta.profiles}
          go={ta.openMasters}
        />
        <Stat
          to="/admin/catalogue"
          value={figures && ta.ofTotal(figures.orderable, figures.total)}
          label={ta.orderable}
          go={ta.openCatalogue}
        />
        <Stat to="/admin/catalogue" value={figures && String(figures.flagged)} label={ta.flagged} go={ta.openCatalogue} />
      </div>

      <div className="two-col">
        <Panel title={ta.oldest} load={queue} empty={ta.noneWaiting}>
          {(page: Page<ReviewQueueItem>) =>
            page.items.slice(0, SHOWN).map((item) => (
              <div key={`${item.kind}-${item.item_id}`} className="queue-row">
                <span>
                  <strong>
                    {item.w_id && <code>{item.w_id}</code>} {item.name}
                  </strong>
                  <span className="muted row-sub">
                    {item.master_name} · {t.reviewQueue.kinds[item.kind]} · {ta.since(rigaDate(item.since))}
                  </span>
                </span>
                <Link to={`/admin/masters/${item.master_id}`} aria-label={`${t.reviewQueue.openMaster}: ${item.master_name}`}>
                  {t.masterHome.open}
                </Link>
              </div>
            ))
          }
        </Panel>
        <Panel title={ta.profilesList} load={profiles} empty={ta.noProfiles}>
          {(page: Page<AdminMasterListItem>) =>
            page.items.slice(0, SHOWN).map((m) => (
              <div key={m.id} className="queue-row">
                <span>
                  <strong>{m.full_name}</strong>
                  <span className="muted row-sub">
                    {t.admin.registered} {rigaDate(m.registered_at)}
                  </span>
                </span>
                <Link to={`/admin/masters/${m.id}`}>{t.masterHome.open}</Link>
              </div>
            ))
          }
        </Panel>
      </div>

      <StatsPanel />

      {tree.error && (
        <p role="alert" className="error">
          {tree.error}
        </p>
      )}
      {figures && (
        <section className="card section-gap" aria-labelledby="ad-catalogue">
          <h2 id="ad-catalogue">{t.catalogue.summary}</h2>
          <ul className="cat-summary">
            <li className="badge badge-success">{t.catalogue.orderableCount(figures.orderable, figures.total)}</li>
            <li className="badge">{t.catalogue.draftCount(figures.drafts)}</li>
            <li className="badge badge-warning">{t.catalogue.flaggedCount(figures.flagged)}</li>
            <li className="badge badge-danger">{t.catalogue.holdCount(figures.hold)}</li>
          </ul>
          <p className="muted">{ta.catalogueNote}</p>
        </section>
      )}
    </section>
  )
}

function Stat({
  to,
  value,
  label,
  go,
  attention = false,
}: {
  to: string
  value: string | null
  label: string
  go: string
  attention?: boolean
}) {
  return (
    <Link to={to} className="stat">
      <span className={attention && value && value !== '0' ? 'num attn' : 'num'}>{value ?? '…'}</span>
      <span className="lbl">{label}</span>
      <span className="go">
        {go} <span aria-hidden="true">→</span>
      </span>
    </Link>
  )
}

function Panel<T>({
  title,
  load,
  empty,
  children,
}: {
  title: string
  load: Load<Page<T>>
  empty: string
  children: (page: Page<T>) => ReactNode
}) {
  return (
    <section className="card" aria-label={title}>
      <h2>{title}</h2>
      {load.error ? (
        <p role="alert" className="error">
          {load.error}
        </p>
      ) : !load.data ? (
        <Skeleton />
      ) : load.data.items.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        children(load.data)
      )}
    </section>
  )
}
