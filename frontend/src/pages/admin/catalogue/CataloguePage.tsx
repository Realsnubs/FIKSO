import { Skeleton } from '../../../components/Skeleton'
import { usePageTitle } from '../../../i18n/usePageTitle'
import { useState, type FormEvent } from 'react'
import { catalogueApi } from '../../../api/endpoints'
import { AdminNav } from '../../../components/AdminNav'
import { t } from '../../../i18n/lv'
import type {
  BasisItem,
  CatalogueTree,
  Qualification,
  TreeCategory as Category,
  TreeService as Service,
  TreeSpecialisation as Specialisation,
} from '../../../types/catalogue'
import { ImpactDialog, type PendingChange } from './ImpactDialog'
import { EntryForm, OrderButtons, StatusBadge, StatusControl, type FieldSpec } from './shared'
import { GROUP_TRANSITIONS, SERVICE_TRANSITIONS, moved, reasonText, useCatalogueTree, useMutation } from './state'

const HIDDEN = new Set(['archived', 'rejected'])
const tc = t.catalogue

type Run = (action: () => Promise<unknown>) => Promise<boolean>

interface Ctx {
  tree: CatalogueTree
  busy: boolean
  run: Run
  panel: string | null
  toggle: (key: string) => void
  reorderable: boolean
  /** Every change that affects availability goes through the impact preview (R-CAT-18, step 4.6.3). */
  preview: (change: PendingChange) => void
  fail: (message: string) => void
}

function visible<T extends { status: string }>(items: T[]): T[] {
  return items.filter((i) => !HIDDEN.has(i.status))
}

function matches(text: string, query: string): boolean {
  return text.toLowerCase().includes(query)
}

export function CataloguePage() {
  usePageTitle(tc.title)
  const { tree, loadError, reload } = useCatalogueTree()
  const { busy, error, run, fail } = useMutation(reload)
  const [pending, setPending] = useState<PendingChange | null>(null)
  const [query, setQuery] = useState('')
  const [showHidden, setShowHidden] = useState(false)
  const [panel, setPanel] = useState<string | null>(null)
  // "Expand all" opens every node; "Collapse all" remounts the tree so nodes opened by hand close too.
  const [expandAll, setExpandAll] = useState(false)
  const [treeKey, setTreeKey] = useState(0)

  if (loadError) {
    return (
      <section>
        <AdminNav />
        <p role="alert" className="error">
          {loadError}{' '}
          <button type="button" className="button-secondary" onClick={reload}>
            {t.retry}
          </button>
        </p>
      </section>
    )
  }
  if (!tree) return <Skeleton variant="page" />

  const q = query.trim().toLowerCase()
  const ctx: Ctx = {
    tree,
    busy,
    run: async (action) => {
      const ok = await run(action)
      if (ok) setPanel(null)
      return ok
    },
    panel,
    toggle: (key) => setPanel((current) => (current === key ? null : key)),
    // Reordering works on the full list of visible siblings, so it is off while filtering.
    reorderable: !q,
    preview: setPending,
    fail,
  }

  const serviceShown = (s: Service) =>
    (showHidden || !HIDDEN.has(s.status)) && (!q || matches(`${s.w_id} ${s.name}`, q))
  const specShown = (sp: Specialisation) =>
    (showHidden || !HIDDEN.has(sp.status)) && (!q || matches(sp.name, q) || sp.services.some(serviceShown))
  const categories = tree.categories.filter(
    (c) =>
      (showHidden || !HIDDEN.has(c.status)) &&
      (!q || matches(c.name, q) || c.specialisations.some(specShown)),
  )

  return (
    <section className="stack">
      <AdminNav />
      <h1>{tc.title}</h1>
      <p className="muted">{tc.intro}</p>
      {!tree.can_create && <p className="notice">{tc.receiverNotice}</p>}

      <div className="filters">
        <label>
          {tc.search}
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} />
          <span>{tc.showHidden}</span>
        </label>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {tree.can_create && (
        <div>
          <button
            type="button"
            onClick={() => ctx.toggle('add-category')}
            aria-expanded={panel === 'add-category'}
          >
            {tc.addCategory}
          </button>
          {panel === 'add-category' && (
            <EntryForm
              fields={[
                { name: 'name', label: tc.name, kind: 'text', required: true },
                {
                  name: 'description',
                  label: tc.description,
                  kind: 'textarea',
                },
              ]}
              submitLabel={tc.save}
              busy={busy}
              onCancel={() => setPanel(null)}
              onSubmit={(v) => void ctx.run(() => catalogueApi.create('categories', v))}
            />
          )}
        </div>
      )}

      <CatalogueSummary tree={tree} />
      {categories.length > 0 && (
        <div className="actions">
          <button type="button" className="button-secondary button-small" onClick={() => setExpandAll(true)}>
            {tc.expandAll}
          </button>
          <button
            type="button"
            className="button-secondary button-small"
            onClick={() => {
              setExpandAll(false)
              setTreeKey((k) => k + 1)
            }}
          >
            {tc.collapseAll}
          </button>
        </div>
      )}

      {categories.length === 0 && <p className="empty">{tc.empty}</p>}
      <ul className="tree" key={treeKey}>
        {categories.map((category) => (
          <CategoryNode
            key={category.id}
            ctx={ctx}
            category={category}
            specialisations={category.specialisations.filter(specShown)}
            serviceShown={serviceShown}
            forceOpen={Boolean(q) || expandAll}
          />
        ))}
      </ul>
      {pending && (
        <ImpactDialog
          change={pending}
          onApplied={() => {
            setPending(null)
            setPanel(null)
            reload()
          }}
          onConflict={reload}
          onClose={() => setPending(null)}
        />
      )}
    </section>
  )
}

function Actions({ ctx, id, items }: { ctx: Ctx; id: string; items: { key: string; label: string }[] }) {
  return (
    <div className="actions">
      {items.map((item) => {
        const key = `${item.key}:${id}`
        return (
          <button
            key={key}
            type="button"
            className="button-secondary"
            aria-expanded={ctx.panel === key}
            onClick={() => ctx.toggle(key)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}


/** What the tree holds, counted from the tree itself: orderable, drafts, entries to review and HOLD. */
function CatalogueSummary({ tree }: { tree: CatalogueTree }) {
  const services = tree.categories.flatMap((c) => c.specialisations.flatMap((sp) => sp.services))
  const live = services.filter((s) => s.status !== 'archived' && s.status !== 'rejected')
  return (
    <ul className="cat-summary" aria-label={tc.summary}>
      <li className="badge badge-success">{tc.orderableCount(services.filter((s) => s.orderable).length, live.length)}</li>
      <li className="badge">{tc.draftCount(services.filter((s) => s.status === 'draft').length)}</li>
      <li className="badge badge-warning">{tc.flaggedCount(live.filter((s) => s.review_note).length)}</li>
      <li className="badge badge-danger">{tc.holdCount(services.filter((s) => s.status === 'hold').length)}</li>
    </ul>
  )
}

function CategoryNode({
  ctx,
  category,
  specialisations,
  serviceShown,
  forceOpen,
}: {
  ctx: Ctx
  category: Category
  specialisations: Specialisation[]
  serviceShown: (s: Service) => boolean
  forceOpen: boolean
}) {
  const siblings = visible(ctx.tree.categories)
  const index = siblings.findIndex((c) => c.id === category.id)
  const actions = [
    { key: 'edit', label: tc.edit },
    { key: 'status', label: tc.status },
    ...(ctx.tree.can_create ? [{ key: 'add-spec', label: tc.addSpecialisation }] : []),
  ]
  return (
    <li className="card">
      <details open={forceOpen || undefined}>
        <summary>
          <strong>{category.name}</strong> <StatusBadge status={category.status} />{' '}
          <span className="muted">({category.specialisations.length})</span>
        </summary>
        <div className="node-tools">
          {ctx.reorderable && index >= 0 && (
            <OrderButtons
              index={index}
              count={siblings.length}
              busy={ctx.busy}
              onMove={(d) => void ctx.run(() => catalogueApi.reorder('', moved(siblings, index, d)))}
            />
          )}
          <Actions ctx={ctx} id={category.id} items={actions} />
        </div>
        {category.description && <p className="muted">{category.description}</p>}
        {ctx.panel === `edit:${category.id}` && (
          <EntryForm
            fields={[
              { name: 'name', label: tc.name, kind: 'text', required: true },
              { name: 'description', label: tc.description, kind: 'textarea' },
            ]}
            initial={{ name: category.name, description: category.description }}
            submitLabel={tc.save}
            busy={ctx.busy}
            onCancel={() => ctx.toggle(`edit:${category.id}`)}
            onSubmit={(v) => void ctx.run(() => catalogueApi.update('categories', category.id, v, category.version))}
          />
        )}
        {ctx.panel === `status:${category.id}` && (
          <StatusControl
            key={category.status}
            current={category.status}
            transitions={GROUP_TRANSITIONS}
            busy={ctx.busy}
            onChange={(s, r) =>
              ctx.preview({
                request: { entity: 'category', id: category.id, change: { kind: 'status', status: s, reason: r || null } },
                apply: (basis, version) => catalogueApi.setStatus('categories', category.id, s, r, version, basis),
              })
            }
          />
        )}
        {ctx.panel === `add-spec:${category.id}` && (
          <EntryForm
            fields={[
              { name: 'name', label: tc.name, kind: 'text', required: true },
              { name: 'description', label: tc.description, kind: 'textarea' },
            ]}
            submitLabel={tc.save}
            busy={ctx.busy}
            onCancel={() => ctx.toggle(`add-spec:${category.id}`)}
            onSubmit={(v) =>
              void ctx.run(() =>
                catalogueApi.create('specialisations', {
                  ...v,
                  category_id: category.id,
                }),
              )
            }
          />
        )}
        <ul className="tree">
          {specialisations.map((spec) => (
            <SpecialisationNode
              key={spec.id}
              ctx={ctx}
              category={category}
              spec={spec}
              services={spec.services.filter(serviceShown)}
              forceOpen={forceOpen}
            />
          ))}
        </ul>
      </details>
    </li>
  )
}

function SpecialisationNode({
  ctx,
  category,
  spec,
  services,
  forceOpen,
}: {
  ctx: Ctx
  category: Category
  spec: Specialisation
  services: Service[]
  forceOpen: boolean
}) {
  const siblings = visible(category.specialisations)
  const index = siblings.findIndex((s) => s.id === spec.id)
  const flagged = spec.services.filter((s) => s.review_note && !HIDDEN.has(s.status)).length
  const categoryOptions = visible(ctx.tree.categories).map((c) => ({
    value: c.id,
    label: c.name,
  }))
  const fields: FieldSpec[] = [
    { name: 'name', label: tc.name, kind: 'text', required: true },
    { name: 'description', label: tc.description, kind: 'textarea' },
    {
      name: 'category_id',
      label: tc.category,
      kind: 'select',
      options: categoryOptions,
    },
    {
      name: 'qualification_required',
      label: tc.qualificationRequired,
      kind: 'checkbox',
      hint: tc.wholeSpecialisationHint,
    },
  ]
  const actions = [
    { key: 'edit', label: tc.edit },
    { key: 'status', label: tc.status },
    { key: 'req', label: tc.requirements },
    ...(ctx.tree.can_create ? [{ key: 'add-service', label: tc.addService }] : []),
  ]
  return (
    <li className="node">
      <details open={forceOpen || undefined}>
        <summary>
          {spec.name} <StatusBadge status={spec.status} />{' '}
          <span className="muted">
            ({spec.services.length} {tc.services})
          </span>
          {flagged > 0 && <span className="badge badge-flag"> ⚑ {flagged}</span>}
        </summary>
        <div className="node-tools">
          {ctx.reorderable && index >= 0 && (
            <OrderButtons
              index={index}
              count={siblings.length}
              busy={ctx.busy}
              onMove={(d) =>
                void ctx.run(() =>
                  catalogueApi.reorder(
                    `categories/${category.id}/specialisations`,
                    moved(siblings, index, d),
                  ),
                )
              }
            />
          )}
          <Actions ctx={ctx} id={spec.id} items={actions} />
        </div>
        {spec.description && <p className="muted">{spec.description}</p>}
        {ctx.panel === `edit:${spec.id}` && (
          <EntryForm
            fields={fields}
            initial={{
              name: spec.name,
              description: spec.description,
              category_id: spec.category_id,
              qualification_required: spec.qualification_required,
            }}
            submitLabel={tc.save}
            busy={ctx.busy}
            onCancel={() => ctx.toggle(`edit:${spec.id}`)}
            onSubmit={(v) => saveSpecialisation(ctx, spec, v)}
          />
        )}
        {ctx.panel === `status:${spec.id}` && (
          <StatusControl
            key={spec.status}
            current={spec.status}
            transitions={GROUP_TRANSITIONS}
            busy={ctx.busy}
            onChange={(s, r) =>
              ctx.preview({
                request: { entity: 'specialisation', id: spec.id, change: { kind: 'status', status: s, reason: r || null } },
                apply: (basis, version) => catalogueApi.setStatus('specialisations', spec.id, s, r, version, basis),
              })
            }
          />
        )}
        {ctx.panel === `req:${spec.id}` && (
          <RequirementsEditor
            ctx={ctx}
            selected={spec.qualification_ids}
            onSave={(ids) =>
              ctx.preview({
                request: { entity: 'specialisation', id: spec.id, change: { kind: 'requirements', qualification_ids: ids } },
                apply: (basis, version) => catalogueApi.setRequirements('specialisations', spec.id, ids, version, basis),
              })
            }
          />
        )}
        {ctx.panel === `add-service:${spec.id}` && (
          <EntryForm
            fields={serviceFields(ctx.tree, false)}
            submitLabel={tc.save}
            busy={ctx.busy}
            onCancel={() => ctx.toggle(`add-service:${spec.id}`)}
            onSubmit={(v) =>
              void ctx.run(() =>
                catalogueApi.create('services', {
                  ...toServiceBody(v),
                  specialisation_id: spec.id,
                }),
              )
            }
          />
        )}
        <ul className="service-list">
          {services.map((service) => (
            <ServiceNode key={service.id} ctx={ctx} spec={spec} service={service} />
          ))}
        </ul>
      </details>
    </li>
  )
}

/**
 * An edit that moves the entry or changes `qualification_required` affects availability: it is previewed and
 * then saved with the preview's basis. Name, description and other fields are saved directly (with the version).
 * The preview describes one change at a time, so a move and a flag change are saved separately.
 */
function saveEdit(
  ctx: Ctx,
  entity: 'specialisation' | 'service',
  id: string,
  body: Record<string, unknown>,
  moved: string | null,
  flagChanged: boolean,
  save: (version: number, basis?: BasisItem[]) => Promise<unknown>,
  version: number,
) {
  if (moved !== null && flagChanged) {
    ctx.fail(t.impact.separately)
    return
  }
  if (moved !== null) {
    ctx.preview({ request: { entity, id, change: { kind: 'move', target_id: moved } }, apply: (basis, v) => save(v, basis) })
  } else if (flagChanged) {
    const value = Boolean(body.qualification_required)
    ctx.preview({
      request: { entity, id, change: { kind: 'qualification_required', value } },
      apply: (basis, v) => save(v, basis),
    })
  } else {
    void ctx.run(() => save(version))
  }
}

function saveSpecialisation(ctx: Ctx, spec: Specialisation, body: Record<string, unknown>) {
  saveEdit(
    ctx,
    'specialisation',
    spec.id,
    body,
    body.category_id !== spec.category_id ? String(body.category_id) : null,
    Boolean(body.qualification_required) !== spec.qualification_required,
    (version, basis) => catalogueApi.update('specialisations', spec.id, body, version, basis),
    spec.version,
  )
}

function saveService(ctx: Ctx, service: Service, body: Record<string, unknown>) {
  saveEdit(
    ctx,
    'service',
    service.id,
    body,
    body.specialisation_id !== service.specialisation_id ? String(body.specialisation_id) : null,
    Boolean(body.qualification_required) !== service.qualification_required,
    (version, basis) => catalogueApi.update('services', service.id, body, version, basis),
    service.version,
  )
}

function serviceFields(tree: CatalogueTree, withParent: boolean): FieldSpec[] {
  const specOptions = tree.categories.flatMap((c) =>
    visible(c.specialisations).map((s) => ({
      value: s.id,
      label: `${c.name} › ${s.name}`,
    })),
  )
  return [
    { name: 'name', label: tc.name, kind: 'text', required: true },
    { name: 'description', label: tc.description, kind: 'textarea' },
    ...(withParent
      ? [
          {
            name: 'specialisation_id',
            label: tc.specialisation,
            kind: 'select',
            options: specOptions,
          } as const,
        ]
      : []),
    {
      name: 'qualification_required',
      label: tc.qualificationRequired,
      kind: 'checkbox',
    },
    { name: 'high_risk', label: tc.highRisk, kind: 'checkbox' },
    { name: 'restrictions', label: tc.restrictions, kind: 'textarea' },
  ]
}

function toServiceBody(values: Record<string, unknown>): Record<string, unknown> {
  const { high_risk, ...rest } = values
  return { ...rest, risk_level: high_risk ? 'high' : 'normal' }
}

/** Availability exactly as the backend computed it (R-CAT-03); the UI decides nothing itself. */
function Availability({ service }: { service: Service }) {
  return (
    <div className="availability">
      <p className={service.orderable ? 'muted' : 'error'}>
        <strong>{service.orderable ? tc.orderable : tc.notOrderable}</strong> · {tc.eligibleMasters}:{' '}
        {service.eligible_masters}
      </p>
      {service.orderable_reasons.length > 0 && (
        <ul aria-label={tc.notOrderableReasons} className="reasons">
          {service.orderable_reasons.map((reason) => (
            <li key={reason.code}>{reasonText(reason)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ServiceNode({ ctx, spec, service }: { ctx: Ctx; spec: Specialisation; service: Service }) {
  const siblings = visible(spec.services)
  const index = siblings.findIndex((s) => s.id === service.id)
  const [holdConfirmed, setHoldConfirmed] = useState(false)
  const fields: FieldSpec[] = [
    ...serviceFields(ctx.tree, true),
    { name: 'review_note', label: tc.reviewNote, kind: 'textarea' },
  ]
  const actions = [
    { key: 'edit', label: tc.edit },
    { key: 'status', label: tc.status },
    { key: 'req', label: tc.requirements },
  ]

  function handleHold(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const reason = String(new FormData(event.currentTarget).get('reason'))
    ctx.preview({
      request: { entity: 'service', id: service.id, change: { kind: 'activate_hold', reason } },
      apply: (basis, version) => catalogueApi.activateHold(service.id, reason, version, basis),
    })
  }

  return (
    <li className="service">
      <div className="service-head">
        <code>{service.w_id}</code> <span>{service.name}</span> <StatusBadge status={service.status} />
        {service.risk_level === 'high' && <span className="badge badge-warning">{tc.highRisk}</span>}
      </div>
      <Availability service={service} />
      {service.review_note && (
        <p className="notice">
          <strong>⚑ {tc.flagged}:</strong> {service.review_note}
        </p>
      )}
      {service.qualification_required && (
        <p className={service.qualifications_ready ? 'muted' : 'error'}>
          {tc.qualificationRequired}
          {!service.qualifications_ready && ` — ${tc.notReady}`}
        </p>
      )}
      <div className="node-tools">
        {ctx.reorderable && index >= 0 && (
          <OrderButtons
            index={index}
            count={siblings.length}
            busy={ctx.busy}
            onMove={(d) =>
              void ctx.run(() =>
                catalogueApi.reorder(`specialisations/${spec.id}/services`, moved(siblings, index, d)),
              )
            }
          />
        )}
        <Actions ctx={ctx} id={service.id} items={actions} />
      </div>
      {ctx.panel === `edit:${service.id}` && (
        <EntryForm
          fields={fields}
          initial={{
            name: service.name,
            description: service.description,
            specialisation_id: service.specialisation_id,
            qualification_required: service.qualification_required,
            high_risk: service.risk_level === 'high',
            restrictions: service.restrictions,
            review_note: service.review_note,
          }}
          submitLabel={tc.save}
          busy={ctx.busy}
          onCancel={() => ctx.toggle(`edit:${service.id}`)}
          onSubmit={(v) => saveService(ctx, service, toServiceBody(v))}
        />
      )}
      {ctx.panel === `status:${service.id}` && (
        <>
          <StatusControl
            key={service.status}
            current={service.status}
            transitions={SERVICE_TRANSITIONS}
            busy={ctx.busy}
            onChange={(s, r) =>
              ctx.preview({
                request: { entity: 'service', id: service.id, change: { kind: 'status', status: s, reason: r || null } },
                apply: (basis, version) => catalogueApi.setStatus('services', service.id, s, r, version, basis),
              })
            }
          />
          {service.status === 'hold' && (
            <form className="inline-form" onSubmit={handleHold}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={holdConfirmed}
                  onChange={(e) => setHoldConfirmed(e.target.checked)}
                />
                <span>{tc.holdConfirm}</span>
              </label>
              <label>
                {tc.reason}
                <input name="reason" required minLength={3} maxLength={500} />
              </label>
              <button type="submit" className="button-danger" disabled={ctx.busy || !holdConfirmed}>
                {tc.activateHold}
              </button>
            </form>
          )}
        </>
      )}
      {ctx.panel === `req:${service.id}` && (
        <RequirementsEditor
          ctx={ctx}
          selected={service.qualification_ids}
          onSave={(ids) =>
            ctx.preview({
              request: { entity: 'service', id: service.id, change: { kind: 'requirements', qualification_ids: ids } },
              apply: (basis, version) => catalogueApi.setRequirements('services', service.id, ids, version, basis),
            })
          }
        />
      )}
    </li>
  )
}

function RequirementsEditor({
  ctx,
  selected,
  onSave,
}: {
  ctx: Ctx
  selected: string[]
  onSave: (ids: string[]) => void
}) {
  const options: Qualification[] = ctx.tree.qualifications.filter(
    (q) => q.status !== 'archived' || selected.includes(q.id),
  )
  if (options.length === 0) return <p className="muted">{tc.noQualifications}</p>

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSave(new FormData(event.currentTarget).getAll('qualification').map(String))
  }

  return (
    <form className="entry-form" onSubmit={handleSubmit}>
      <fieldset>
        <legend>{tc.requirements}</legend>
        {options.map((q) => (
          <label key={q.id} className="checkbox">
            <input
              type="checkbox"
              name="qualification"
              value={q.id}
              defaultChecked={selected.includes(q.id)}
            />
            <span>
              {q.name} <StatusBadge status={q.status} />
            </span>
          </label>
        ))}
      </fieldset>
      <button type="submit" disabled={ctx.busy}>
        {tc.saveRequirements}
      </button>
    </form>
  )
}
