import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { workApi, type OrderAction } from '../../api/work'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { MasterNav } from '../../components/MasterNav'
import { Skeleton } from '../../components/Skeleton'
import { StatusBadge } from '../../components/StatusBadge'
import { rigaDateTime } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { MasterOrder, WorksheetData } from '../../types/work'
import { duration } from '../../work/format'
import { useAction, useLoad } from '../../work/hooks'
import { Countdown, ErrorLine, Money, PrivatePhoto } from '../../work/parts'
import { PlaceFacts } from '../../work/places'

const tm = t.app.masterOrder
const tw = t.app.work

interface Material {
  name: string
  quantity: string
  unit: string
  amount_eur: string
}

function sheetForm(sheet: WorksheetData | null) {
  return {
    work_description: sheet?.work_description ?? '',
    limitations_explained: sheet?.limitations_explained ?? '',
    is_temporary_repair: sheet?.is_temporary_repair ?? false,
    internal_notes: sheet?.internal_notes ?? '',
    external_costs_eur: sheet?.external_costs_eur ?? '0.00',
    materials: (sheet?.materials ?? []).map((m) => ({ name: m.name, quantity: m.quantity, unit: m.unit ?? '', amount_eur: m.amount_eur })) as Material[],
  }
}

function nextActions(order: MasterOrder): OrderAction[] {
  switch (order.status) {
    case 'accepted':
    case 'scheduled':
      return ['depart']
    case 'en_route':
      return order.timeline.arrived_at ? ['start'] : ['arrive', 'start']
    case 'in_progress':
      if (order.timeline.work_completed_at) return []
      return order.work_running ? ['pause', 'finish'] : ['resume', 'finish']
    default:
      return []
  }
}

/** One order of the master: details, the status buttons, the work sheet and the calculation after closing. */
export function MasterOrderPage() {
  const { id = '' } = useParams()
  usePageTitle(tw.title)
  const { data: order, setData, error, loading } = useLoad(() => workApi.order(id), 30000, [id])
  const action = useAction()
  const [form, setForm] = useState<ReturnType<typeof sheetForm> | null>(null)
  const [saved, setSaved] = useState(false)
  const [confirmFinal, setConfirmFinal] = useState(false)
  const [cancelReason, setCancelReason] = useState<string | null>(null)

  if (loading && !order) return <Skeleton variant="page" />
  if (!order) return <ErrorLine message={error} />

  const sheet = form ?? sheetForm(order.worksheet)
  const editable = order.status === 'in_progress' && order.worksheet?.state === 'draft'
  const run = async (fn: () => Promise<MasterOrder>) => {
    const result = await action.run(fn)
    if (result) setData(result)
    return result
  }
  const saveSheet = async () => {
    const result = await run(() =>
      workApi.worksheet(order.id, {
        ...sheet,
        external_costs_eur: Number(sheet.external_costs_eur || 0).toFixed(2),
        materials: sheet.materials
          .filter((m) => m.name.trim())
          .map((m) => ({ ...m, amount_eur: Number(m.amount_eur || 0).toFixed(2), quantity: m.quantity || '1', unit: m.unit || undefined })),
      }),
    )
    if (result) {
      setForm(null)
      setSaved(true)
    }
    return result
  }
  const labels: Record<OrderAction, string> = {
    accept: tw.accept, depart: tm.depart, arrive: tm.arrive, start: tm.start,
    pause: tm.pause, resume: tm.resume, finish: tm.finish, finalise: tm.finalise,
  }
  const result = order.worksheet?.state === 'finalised' ? order.worksheet : null

  return (
    <section>
      <MasterNav />
      <Link to="/master/darbs" className="back-link">
        <span aria-hidden="true">←</span> {tm.back}
      </Link>
      <div className="page-head">
        <h1>
          <code>{order.service.w_id}</code> {order.service.name}
        </h1>
        <StatusBadge label={t.app.orderStatus[order.status] ?? order.status} tone={order.status === 'completed' ? 'success' : 'info'} />
      </div>
      <ErrorLine message={action.error} />

      {order.status === 'offered' && (
        <section className="card stack">
          {order.offer_expires_at && <Countdown until={order.offer_expires_at} label={tw.answerIn} />}
          <div className="actions">
            <button type="button" disabled={action.busy} onClick={() => void run(() => workApi.action(order.id, 'accept'))}>
              {tw.accept}
            </button>
            <button type="button" className="button-secondary" disabled={action.busy} onClick={() => void run(() => workApi.decline(order.id))}>
              {tw.decline}
            </button>
          </div>
          <p className="hint">{tm.hiddenUntilAccepted}</p>
        </section>
      )}

      <section className="card stack" aria-labelledby="mo-job">
        <h2 id="mo-job">{t.app.request.description}</h2>
        <p>{order.description}</p>
        <p className="muted">
          {order.order_type === 'reserved' && order.scheduled_start && order.scheduled_end
            ? t.app.request.window(rigaDateTime(order.scheduled_start), rigaDateTime(order.scheduled_end))
            : tw.immediate}
        </p>
        <dl className="summary-list">
          <PlaceFacts city={order.city} communicationLanguage={order.communication_language} />
        </dl>
        {order.photos.length > 0 && (
          <ul className="thumbs" aria-label={t.app.request.photos}>
            {order.photos.map((p, i) => (
              <li key={p.id}>
                <PrivatePhoto load={() => workApi.photo(order.id, p.id)} alt={`${t.app.request.photos} ${i + 1}`} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {order.client && order.address && (
        <section className="card stack" aria-labelledby="mo-client">
          <h2 id="mo-client">{tm.client}</h2>
          <p>
            <strong>{order.client.name}</strong>
            {order.client.phone && (
              <>
                {' · '}
                <a href={`tel:${order.client.phone}`}>{order.client.phone}</a>
              </>
            )}
          </p>
          <p>
            {order.address.address}
            {order.address.flat && ` · ${order.address.flat}`}
          </p>
          {order.address.access_info && (
            <p className="muted">
              {tm.access}: {order.address.access_info}
            </p>
          )}
          <a href={`https://www.google.com/maps/dir/?api=1&destination=${order.address.lat},${order.address.lon}`} target="_blank" rel="noreferrer">
            {tm.navigate}
          </a>
        </section>
      )}

      {nextActions(order).length > 0 && (
        <section className="card stack">
          {order.status === 'in_progress' && (
            <p>
              <strong>{tm.workTime}:</strong> {duration(order.billable_seconds)} · {order.work_running ? tm.running : tm.paused}
            </p>
          )}
          <div className="actions">
            {nextActions(order).map((a) => (
              <button key={a} type="button" disabled={action.busy} className={a === 'pause' ? 'button-secondary' : undefined} onClick={() => void run(() => workApi.action(order.id, a))}>
                {labels[a]}
              </button>
            ))}
            {['accepted', 'scheduled', 'en_route'].includes(order.status) && (
              <button type="button" className="button-ghost" onClick={() => setCancelReason('')}>
                {tm.cancelOrder}
              </button>
            )}
          </div>
        </section>
      )}

      {editable && (
        <section className="card stack" aria-labelledby="mo-sheet">
          <h2 id="mo-sheet">{tm.worksheet}</h2>
          <div className="field">
            <label htmlFor="mo-desc">{tm.workDescription}</label>
            <textarea id="mo-desc" rows={4} value={sheet.work_description} onChange={(e) => setForm({ ...sheet, work_description: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="mo-lim">{tm.limitations}</label>
            <textarea id="mo-lim" rows={2} value={sheet.limitations_explained} onChange={(e) => setForm({ ...sheet, limitations_explained: e.target.value })} />
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={sheet.is_temporary_repair} onChange={(e) => setForm({ ...sheet, is_temporary_repair: e.target.checked })} /> {tm.temporary}
          </label>
          <fieldset className="stack">
            <legend>{tm.materials}</legend>
            {sheet.materials.map((m, i) => (
              <div key={i} className="material-row">
                <input aria-label={tm.material} placeholder={tm.material} value={m.name} onChange={(e) => setForm({ ...sheet, materials: sheet.materials.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                <input aria-label={tm.quantity} placeholder={tm.quantity} inputMode="decimal" value={m.quantity} onChange={(e) => setForm({ ...sheet, materials: sheet.materials.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)) })} />
                <input aria-label={tm.unit} placeholder={tm.unit} value={m.unit} onChange={(e) => setForm({ ...sheet, materials: sheet.materials.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)) })} />
                <input aria-label={tm.amount} placeholder={tm.amount} inputMode="decimal" value={m.amount_eur} onChange={(e) => setForm({ ...sheet, materials: sheet.materials.map((x, j) => (j === i ? { ...x, amount_eur: e.target.value } : x)) })} />
                <button type="button" className="button-ghost button-small" onClick={() => setForm({ ...sheet, materials: sheet.materials.filter((_, j) => j !== i) })}>
                  {tm.remove}
                </button>
              </div>
            ))}
            <button type="button" className="button-secondary button-small" onClick={() => setForm({ ...sheet, materials: [...sheet.materials, { name: '', quantity: '1', unit: '', amount_eur: '0.00' }] })}>
              {tm.addMaterial}
            </button>
          </fieldset>
          <div className="field">
            <label htmlFor="mo-ext">{tm.external}</label>
            <input id="mo-ext" inputMode="decimal" value={sheet.external_costs_eur} onChange={(e) => setForm({ ...sheet, external_costs_eur: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="mo-int">{tm.internal}</label>
            <textarea id="mo-int" rows={2} value={sheet.internal_notes} onChange={(e) => setForm({ ...sheet, internal_notes: e.target.value })} />
          </div>
          <p className="hint">{tm.rateInfo(order.terms.hourly_rate_eur, order.terms.minimum_order_eur)}</p>
          <p className="hint">{tm.minimumNote}</p>
          <div className="actions">
            <button type="button" className="button-secondary" disabled={action.busy} onClick={() => void saveSheet()}>
              {tm.saveSheet}
            </button>
            {order.timeline.work_completed_at && (
              <button type="button" disabled={action.busy} onClick={() => setConfirmFinal(true)}>
                {tm.finalise}
              </button>
            )}
            {saved && !form && <span className="ok">{tm.saved}</span>}
          </div>
        </section>
      )}

      {result && (
        <section className="card stack" aria-labelledby="mo-result">
          <h2 id="mo-result">{tm.result}</h2>
          <dl className="summary-list">
            <dt>{tm.workTime}</dt>
            <dd>{duration(result.billable_seconds ?? 0)}</dd>
            {result.travel_minutes != null && (
              <>
                <dt>{tm.travel}</dt>
                <dd>{duration(result.travel_minutes * 60)}</dd>
              </>
            )}
            <dt>{tm.labour}</dt>
            <dd>
              <Money value={result.labour_amount_eur} />
            </dd>
            <dt>{t.app.request.materials}</dt>
            <dd>
              <Money value={result.materials_amount_eur} />
            </dd>
            <dt>{tm.clientPays}</dt>
            <dd>
              <Money value={String(Number(result.labour_amount_eur ?? 0) + Number(result.materials_amount_eur) + Number(result.external_costs_eur))} />
            </dd>
            <dt>{tm.commission}</dt>
            <dd>
              <Money value={result.commission_eur} />
            </dd>
          </dl>
          <p className="hint">{tm.minimumNote}</p>
        </section>
      )}

      {confirmFinal && (
        <ConfirmDialog
          title={tm.finalise}
          text={tm.finaliseConfirm}
          confirmLabel={tm.finalise}
          confirmTone="primary"
          busy={action.busy}
          narrow
          onCancel={() => setConfirmFinal(false)}
          onConfirm={async () => {
            if (form && !(await saveSheet())) return
            setConfirmFinal(false)
            await run(() => workApi.action(order.id, 'finalise'))
          }}
        />
      )}
      {cancelReason !== null && (
        <ConfirmDialog
          title={tm.cancelOrder}
          confirmLabel={tm.cancelOrder}
          busy={action.busy}
          confirmDisabled={cancelReason.trim().length < 3}
          narrow
          onCancel={() => setCancelReason(null)}
          onConfirm={async () => {
            const done = await run(() => workApi.cancel(order.id, cancelReason.trim()))
            if (done) setCancelReason(null)
          }}
        >
          <label htmlFor="mo-cancel">{tm.cancelReason}</label>
          <textarea id="mo-cancel" rows={3} value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
        </ConfirmDialog>
      )}
    </section>
  )
}
