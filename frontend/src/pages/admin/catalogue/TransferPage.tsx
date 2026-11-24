import { usePageTitle } from '../../../i18n/usePageTitle'
import { useState, type ChangeEvent } from 'react'
import { catalogueApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { errorMessage, t } from '../../../i18n/lv'
import type { PlanEntry, SyncImport } from '../../../types/catalogue'
import { useCatalogueTree } from './state'

const tt = t.transfer

function label(entry: PlanEntry): string {
  return `${entry.w_id ? `${entry.w_id} · ` : ''}${entry.name}`
}

export function TransferPage() {
  usePageTitle(tt.title)
  const { tree } = useCatalogueTree()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SyncImport | null>(null)
  const [updates, setUpdates] = useState<Set<string>>(new Set())
  const [keepActive, setKeepActive] = useState<Set<string>>(new Set())
  const [activeIds, setActiveIds] = useState<Set<string>>(new Set())

  async function guarded(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function download() {
    void guarded(async () => {
      const pkg = await catalogueApi.exportPackage()
      const blob = new Blob([JSON.stringify(pkg, null, 2)], {
        type: 'application/json',
      })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `fikso-catalogue-${new Date().toISOString().slice(0, 10)}.json`
      link.click()
      URL.revokeObjectURL(link.href)
    })
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setResult(null)
    setUpdates(new Set())
    setKeepActive(new Set())
    let pkg: {
      services?: { id: string; status: string }[]
      categories?: { id: string; status: string }[]
      specialisations?: { id: string; status: string }[]
    }
    try {
      pkg = JSON.parse(await file.text())
    } catch {
      setError(tt.invalidFile)
      return
    }
    const entries = [...(pkg.categories ?? []), ...(pkg.specialisations ?? []), ...(pkg.services ?? [])]
    setActiveIds(new Set(entries.filter((e) => e.status === 'active').map((e) => e.id)))
    await guarded(async () => setResult(await catalogueApi.previewImport(pkg)))
  }

  function toggle(set: Set<string>, id: string, update: (s: Set<string>) => void) {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    update(next)
  }

  function apply() {
    if (!result) return
    void guarded(async () =>
      setResult(await catalogueApi.applyImport(result.id, [...updates], [...keepActive])),
    )
  }

  const plan = result?.preview
  const pending = result?.status === 'previewed'
  const keepable = (entry: PlanEntry) => activeIds.has(entry.id) && entry.kind !== 'qualification'

  return (
    <section className="stack">
      <AdminNav />
      <h1>{tt.title}</h1>
      <p className="muted">{tt.intro}</p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="card stack">
        <h2>{tt.exportTitle}</h2>
        <p className="muted">{tt.exportHint}</p>
        <div>
          <button type="button" onClick={download} disabled={busy}>
            {tt.exportButton}
          </button>
        </div>
      </section>

      {tree?.catalogue_role === 'receiver' && (
        <section className="card stack">
          <h2>{tt.importTitle}</h2>
          <p className="muted">{tt.importHint}</p>
          <div className="field">
            <label htmlFor="package-file">{tt.file}</label>
            <input id="package-file" type="file" accept="application/json,.json" onChange={handleFile} />
          </div>

          {plan && (
            <div className="stack" aria-live="polite">
              {result.status === 'applied' && <p className="notice notice-approved">{tt.applied}</p>}
              {plan.conflicts.length > 0 && (
                <div role="alert">
                  <h3 className="error">
                    {tt.conflicts} ({plan.conflicts.length})
                  </h3>
                  <ul>
                    {plan.conflicts.map((c) => (
                      <li key={c.id}>
                        {label(c)} — <code>{c.reason}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <h3>
                {tt.create}: {plan.create.length}
              </h3>
              {pending && plan.create.some(keepable) && (
                <ul className="plain">
                  {plan.create.filter(keepable).map((c) => (
                    <li key={c.id}>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={keepActive.has(c.id)}
                          onChange={() => toggle(keepActive, c.id, setKeepActive)}
                        />
                        <span>
                          {label(c)} — {tt.keepActive}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              <h3>
                {tt.update}: {plan.update.length}
              </h3>
              <ul className="plain">
                {plan.update.map((u) => (
                  <li key={u.id}>
                    {u.locally_edited || !pending ? (
                      <span>
                        {label(u)} ({u.changes?.join(', ')}){u.locally_edited && ` — ${tt.locallyEdited}`}
                      </span>
                    ) : (
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={updates.has(u.id)}
                          onChange={() => toggle(updates, u.id, setUpdates)}
                        />
                        <span>
                          {tt.applyUpdate}: {label(u)} ({u.changes?.join(', ')})
                        </span>
                      </label>
                    )}
                  </li>
                ))}
              </ul>
              <p className="muted">
                {tt.unchanged}: {plan.unchanged.length} · {tt.links}: {plan.links_to_add}
              </p>
              {pending && (
                <div>
                  <button type="button" onClick={apply} disabled={busy || plan.conflicts.length > 0}>
                    {tt.apply}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </section>
  )
}
