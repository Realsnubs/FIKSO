import { Skeleton } from '../../../components/Skeleton'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useState } from 'react'
import { catalogueApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { t } from '../../../i18n/lv'
import type { Qualification } from '../../../types/catalogue'
import { EntryForm, StatusBadge, StatusControl, type FieldSpec } from './shared'
import { QUALIFICATION_TRANSITIONS, useCatalogueTree, useMutation } from './state'

const tq = t.qualifications

const fields: FieldSpec[] = [
  { name: 'name', label: t.catalogue.name, kind: 'text', required: true },
  { name: 'description', label: t.catalogue.description, kind: 'textarea' },
  { name: 'requires_document', label: tq.requiresDocument, kind: 'checkbox' },
  {
    name: 'requires_document_number',
    label: tq.requiresDocumentNumber,
    kind: 'checkbox',
  },
  { name: 'requires_expiry_date', label: tq.requiresExpiry, kind: 'checkbox' },
  {
    name: 'max_validity_months',
    label: tq.maxValidity,
    kind: 'number',
    min: 1,
    max: 600,
  },
  { name: 'verifier_instructions', label: tq.instructions, kind: 'textarea' },
]

function initialOf(q: Qualification) {
  return {
    name: q.name,
    description: q.description,
    requires_document: q.requires_document,
    requires_document_number: q.requires_document_number,
    requires_expiry_date: q.requires_expiry_date,
    max_validity_months: q.max_validity_months,
    verifier_instructions: q.verifier_instructions,
  }
}

export function QualificationsPage() {
  usePageTitle(tq.title)
  const { tree, loadError, reload } = useCatalogueTree()
  const { busy, error, run } = useMutation(reload)
  const [panel, setPanel] = useState<string | null>(null)
  const toggle = (key: string) => setPanel((p) => (p === key ? null : key))
  const done = async (action: () => Promise<unknown>) => {
    if (await run(action)) setPanel(null)
  }

  return (
    <section className="stack">
      <AdminNav />
      <h1>{tq.title}</h1>
      <p className="muted">{tq.intro}</p>
      {loadError && (
        <p role="alert" className="error">
          {loadError}{' '}
          <button type="button" className="button-secondary" onClick={reload}>
            {t.retry}
          </button>
        </p>
      )}
      {!tree && !loadError && <Skeleton />}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {tree?.can_create && (
        <div>
          <button type="button" aria-expanded={panel === 'add'} onClick={() => toggle('add')}>
            {tq.add}
          </button>
          {panel === 'add' && (
            <EntryForm
              fields={fields}
              initial={{ requires_document: true }}
              submitLabel={t.catalogue.save}
              busy={busy}
              onCancel={() => setPanel(null)}
              onSubmit={(v) => void done(() => catalogueApi.create('qualifications', v))}
            />
          )}
        </div>
      )}
      {tree && tree.qualifications.length === 0 && <p className="empty">{tq.empty}</p>}
      <ul className="user-list">
        {tree?.qualifications.map((q) => (
          <li key={q.id} className="card stack">
            <div className="user-head">
              <strong>{q.name}</strong>
              <StatusBadge status={q.status} />
            </div>
            {q.description && <p className="muted">{q.description}</p>}
            <ul className="muted rules">
              {q.requires_document && <li>{tq.requiresDocument}</li>}
              {q.requires_document_number && <li>{tq.requiresDocumentNumber}</li>}
              {q.requires_expiry_date && <li>{tq.requiresExpiry}</li>}
              {q.max_validity_months && (
                <li>
                  {tq.maxValidity}: {q.max_validity_months}
                </li>
              )}
            </ul>
            <div className="actions">
              <button type="button" className="button-secondary" onClick={() => toggle(`edit:${q.id}`)}>
                {t.catalogue.edit}
              </button>
              <button type="button" className="button-secondary" onClick={() => toggle(`status:${q.id}`)}>
                {t.catalogue.status}
              </button>
            </div>
            {panel === `edit:${q.id}` && (
              <EntryForm
                fields={fields}
                initial={initialOf(q)}
                submitLabel={t.catalogue.save}
                busy={busy}
                onCancel={() => setPanel(null)}
                onSubmit={(v) => void done(() => catalogueApi.update('qualifications', q.id, v, null))}
              />
            )}
            {panel === `status:${q.id}` && (
              <StatusControl
                key={q.status}
                current={q.status}
                transitions={QUALIFICATION_TRANSITIONS}
                busy={busy}
                onChange={(s, r) => void done(() => catalogueApi.setStatus('qualifications', q.id, s, r, q.version))}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
