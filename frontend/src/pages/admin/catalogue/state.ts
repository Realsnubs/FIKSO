import { useCallback, useEffect, useState } from 'react'
import { catalogueApi } from '../../../api/endpoints'
import { errorMessage, t } from '../../../i18n/lv'
import type { AvailabilityReason, CatalogueTree } from '../../../types/catalogue'

// UX mirror of the backend transition rules (app/services/catalogue.py); the backend stays authoritative.
export const GROUP_TRANSITIONS: Record<string, string[]> = {
  active: ['inactive', 'planned', 'archived'],
  inactive: ['active', 'planned', 'archived'],
  planned: ['active', 'inactive', 'archived'],
  archived: ['inactive'],
}
export const SERVICE_TRANSITIONS: Record<string, string[]> = {
  draft: ['active', 'inactive', 'planned', 'rejected'],
  active: ['inactive', 'planned', 'hold', 'archived'],
  inactive: ['active', 'planned', 'hold', 'archived'],
  planned: ['active', 'inactive', 'hold', 'archived'],
  hold: ['inactive', 'planned', 'archived'],
  rejected: [],
  archived: ['inactive'],
}
export const QUALIFICATION_TRANSITIONS: Record<string, string[]> = {
  draft: ['active', 'archived'],
  active: ['archived'],
  archived: ['active'],
}
export const REASON_REQUIRED = new Set(['rejected', 'archived', 'hold'])

export function useCatalogueTree() {
  const [tree, setTree] = useState<CatalogueTree | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    catalogueApi
      .tree()
      .then((data) => {
        if (cancelled) return
        setTree(data)
        setLoadError(null)
      })
      .catch((err: unknown) => !cancelled && setLoadError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
  return { tree, loadError, reload }
}

/** Runs a mutation, shows its error and reloads the tree on success — and on a version conflict, so the
 * admin sees the current state before trying again. */
export function useMutation(reload: () => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      setBusy(true)
      setError(null)
      try {
        await action()
        reload()
        return true
      } catch (err) {
        setError(errorMessage(err))
        if (typeof err === 'object' && err && 'code' in err && err.code === 'VERSION_CONFLICT') reload()
        return false
      } finally {
        setBusy(false)
      }
    },
    [reload],
  )
  // A message the page shows in the same place as an error from the server.
  const fail = useCallback((message: string) => setError(message), [])
  return { busy, error, run, fail }
}

export function moved<T extends { id: string }>(items: T[], index: number, delta: -1 | 1): string[] {
  const ids = items.map((i) => i.id)
  const [item] = ids.splice(index, 1)
  ids.splice(index + delta, 0, item)
  return ids
}

/** A backend availability reason in Latvian; an unknown code is shown as is, never hidden. */
export function reasonText(reason: AvailabilityReason): string {
  const text = t.availabilityReasons[reason.code] ?? reason.code
  const status = reason.details.status
  return typeof status === 'string' ? `${text} (${t.catalogueStatus[status] ?? status})` : text
}
