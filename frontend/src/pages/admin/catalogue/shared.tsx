import { useState, type FormEvent } from 'react'
import { t } from '../../../i18n/lv'
import { REASON_REQUIRED } from './state'

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-cat-${status}`}>{t.catalogueStatus[status] ?? status}</span>
}

export type FieldSpec =
  | { name: string; label: string; kind: 'text'; required?: boolean }
  | { name: string; label: string; kind: 'textarea' }
  | { name: string; label: string; kind: 'checkbox'; hint?: string }
  | { name: string; label: string; kind: 'number'; min: number; max: number }
  | {
      name: string
      label: string
      kind: 'select'
      options: { value: string; label: string }[]
    }

type Values = Record<string, string | number | boolean | null>

/** Small accessible form for create/edit. Empty texts become null; checkboxes become booleans. */
export function EntryForm({
  fields,
  initial = {},
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  fields: FieldSpec[]
  initial?: Values
  submitLabel: string
  busy: boolean
  onSubmit: (values: Values) => void
  onCancel: () => void
}) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const values: Values = {}
    for (const field of fields) {
      const raw = form.get(field.name)
      if (field.kind === 'checkbox') values[field.name] = raw === 'on'
      else if (field.kind === 'number') values[field.name] = raw ? Number(raw) : null
      else values[field.name] = typeof raw === 'string' && raw.trim() ? raw.trim() : null
    }
    onSubmit(values)
  }

  return (
    <form className="entry-form" onSubmit={handleSubmit}>
      {fields.map((field) => {
        const id = `f-${field.name}`
        const value = initial[field.name]
        if (field.kind === 'checkbox') {
          return (
            <label key={field.name} className="checkbox">
              <input type="checkbox" name={field.name} defaultChecked={Boolean(value)} />
              <span>
                {field.label}
                {field.hint && <span className="hint"> — {field.hint}</span>}
              </span>
            </label>
          )
        }
        return (
          <div key={field.name} className="field">
            <label htmlFor={id}>{field.label}</label>
            {field.kind === 'textarea' ? (
              <textarea
                id={id}
                name={field.name}
                rows={2}
                maxLength={2000}
                defaultValue={(value as string) ?? ''}
              />
            ) : field.kind === 'select' ? (
              <select id={id} name={field.name} defaultValue={(value as string) ?? ''}>
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                name={field.name}
                type={field.kind}
                required={field.kind === 'text' && field.required}
                minLength={field.kind === 'text' ? 2 : undefined}
                maxLength={field.kind === 'text' ? 200 : undefined}
                min={field.kind === 'number' ? field.min : undefined}
                max={field.kind === 'number' ? field.max : undefined}
                defaultValue={value === null || value === undefined ? '' : String(value)}
              />
            )}
          </div>
        )
      })}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {submitLabel}
        </button>
        <button type="button" className="button-secondary" onClick={onCancel}>
          {t.catalogue.cancel}
        </button>
      </div>
    </form>
  )
}

/** Status select limited to allowed transitions; asks for a reason where the backend requires one. */
export function StatusControl({
  current,
  transitions,
  busy,
  onChange,
}: {
  current: string
  transitions: Record<string, string[]>
  busy: boolean
  onChange: (status: string, reason: string) => void
}) {
  const options = transitions[current] ?? []
  const [next, setNext] = useState(options[0] ?? '')
  if (options.length === 0) return null

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onChange(next, String(new FormData(event.currentTarget).get('reason') ?? ''))
  }

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <label>
        {t.catalogue.newStatus}
        <select value={next} onChange={(e) => setNext(e.target.value)}>
          {options.map((s) => (
            <option key={s} value={s}>
              {t.catalogueStatus[s]}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t.catalogue.reason}
        <input name="reason" minLength={3} maxLength={500} required={REASON_REQUIRED.has(next)} />
      </label>
      <button type="submit" disabled={busy}>
        {t.catalogue.changeStatus}
      </button>
    </form>
  )
}

export function OrderButtons({
  index,
  count,
  busy,
  onMove,
}: {
  index: number
  count: number
  busy: boolean
  onMove: (delta: -1 | 1) => void
}) {
  return (
    <>
      <button
        type="button"
        className="button-icon"
        aria-label={t.catalogue.moveUp}
        disabled={busy || index === 0}
        onClick={() => onMove(-1)}
      >
        ↑
      </button>
      <button
        type="button"
        className="button-icon"
        aria-label={t.catalogue.moveDown}
        disabled={busy || index === count - 1}
        onClick={() => onMove(1)}
      >
        ↓
      </button>
    </>
  )
}
