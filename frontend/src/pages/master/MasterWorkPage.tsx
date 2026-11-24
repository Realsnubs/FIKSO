import { useState } from 'react'
import { Link } from 'react-router'
import { workApi } from '../../api/work'
import { MasterNav } from '../../components/MasterNav'
import { Skeleton } from '../../components/Skeleton'
import { StatusBadge } from '../../components/StatusBadge'
import { rigaDateTime } from '../../i18n/format'
import { useLanguage } from '../../i18n/LanguageContext'
import { t } from '../../i18n/lv'
import { usePageTitle } from '../../i18n/usePageTitle'
import type { MasterOrder, WorkProfile } from '../../types/work'
import { useAction, useLoad } from '../../work/hooks'
import { useLocationSharing } from '../../work/location'
import { Countdown, ErrorLine } from '../../work/parts'
import { NotificationsPanel } from '../../work/Notifications'
import { CityPicker, LanguagePicker } from '../../work/places'
import { cityName, languageName, usePlaces } from '../../work/placesData'

const tw = t.app.work
const tp = t.app.places
const MODES: WorkProfile['availability_mode'][] = ['available_now', 'available_for_reservations', 'unavailable']

function OrderRow({ order, children }: { order: MasterOrder; children?: React.ReactNode }) {
  const { language } = useLanguage()
  const { languages } = usePlaces()
  const when = order.order_type === 'reserved' && order.scheduled_start ? rigaDateTime(order.scheduled_start) : tw.immediate
  return (
    <li className="card stack">
      <div className="card-head">
        <strong className="card-title">
          <code>{order.service.w_id}</code> {order.service.name}
        </strong>
        <StatusBadge label={t.app.orderStatus[order.status] ?? order.status} tone="info" />
      </div>
      <p>{order.description}</p>
      <p className="muted">
        {order.order_type === 'reserved' ? tw.reserved : tw.immediate} · {when} · {cityName(order.city, language)}
      </p>
      <p className="muted">
        {tp.communicationLanguage}: {languageName(order.communication_language, languages, language)}
      </p>
      <div className="actions">
        {children}
        <Link to={`/master/pasutijumi/${order.id}`} className="link-button button-secondary button-small">
          {tw.open}
        </Link>
      </div>
    </li>
  )
}

/**
 * The master's work: availability, work city and communication languages (both required for matching), live location
 * (for ETA only), new offers with the answer timer and active orders.
 */
export function MasterWorkPage() {
  usePageTitle(tw.title)
  const profile = useLoad(() => workApi.profile(), 60000)
  const offers = useLoad(() => workApi.offers(), 15000)
  const active = useLoad(() => workApi.orders('active'), 30000)
  const action = useAction()
  const places = usePlaces()
  const [city, setCity] = useState<string | null>(null)
  const [spoken, setSpoken] = useState<string[] | null>(null)
  const [about, setAbout] = useState<string | null>(null)
  const p = profile.data
  const sharing = useLocationSharing(p?.availability_mode === 'available_now', p?.location_interval_seconds ?? 180, () => void profile.reload())

  if (profile.loading && !p) return <Skeleton variant="page" />
  if (!p) return <ErrorLine message={profile.error} />

  const cityValue = city ?? p.work_city ?? ''
  const spokenValue = spoken ?? p.languages

  async function saveCity() {
    const result = await action.run(() => workApi.setCity(cityValue))
    if (result) {
      profile.setData(result)
      setCity(null)
    }
  }

  async function saveLanguages() {
    const result = await action.run(() => workApi.setLanguages(spokenValue))
    if (result) {
      profile.setData(result)
      setSpoken(null)
    }
  }

  return (
    <section>
      <MasterNav />
      <h1>{tw.title}</h1>
      <ErrorLine message={action.error} />
      <NotificationsPanel />
      {p.commission_limit_reached && <p className="notice notice-rejected">{tw.limitReached}</p>}

      <section className="card stack" aria-labelledby="w-avail">
        <div className="card-head">
          <h2 id="w-avail">{tw.availability}</h2>
          {p.is_busy && <StatusBadge label={tw.busy} tone="warning" />}
        </div>
        <div className="choice-row" role="radiogroup" aria-labelledby="w-avail">
          {MODES.map((mode) => (
            <label key={mode} className={p.availability_mode === mode ? 'on' : undefined}>
              <input
                type="radio"
                name="w-mode"
                checked={p.availability_mode === mode}
                disabled={action.busy}
                onChange={async () => {
                  const result = await action.run(() => workApi.setMode(mode))
                  if (result) profile.setData(result)
                }}
              />{' '}
              {tw.modes[mode]}
            </label>
          ))}
        </div>
        {!p.work_city && <p className="notice">{tp.cityMissing}</p>}
        {p.languages.length === 0 && <p className="notice">{tp.languagesMissing}</p>}
        <div className="stack">
          <strong>{tw.location}</strong>
          {p.availability_mode === 'available_now' && <p className="hint">{tw.locationOn}</p>}
          {p.location_updated_at && <p className="muted">{tw.locationFresh(rigaDateTime(p.location_updated_at))}</p>}
          {p.availability_mode === 'available_now' && !p.location_fresh && <p className="notice">{tw.locationStale}</p>}
          {sharing.denied && <p className="error">{tw.locationDenied}</p>}
        </div>
      </section>

      <section className="card stack" aria-labelledby="w-offers">
        <h2 id="w-offers">{tw.offers}</h2>
        <ErrorLine message={offers.error} />
        {offers.data && offers.data.length > 0 ? (
          <ul className="plain stack">
            {offers.data.map((o) => (
              <OrderRow key={o.id} order={o}>
                {o.offer_expires_at && <Countdown until={o.offer_expires_at} label={tw.answerIn} />}
                <button
                  type="button"
                  disabled={action.busy}
                  onClick={async () => {
                    if (await action.run(() => workApi.action(o.id, 'accept'))) {
                      void offers.reload()
                      void active.reload()
                    }
                  }}
                >
                  {tw.accept}
                </button>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={action.busy}
                  onClick={async () => {
                    if (await action.run(() => workApi.decline(o.id))) void offers.reload()
                  }}
                >
                  {tw.decline}
                </button>
              </OrderRow>
            ))}
          </ul>
        ) : (
          <p className="muted">{tw.noOffers}</p>
        )}
      </section>

      <section className="card stack" aria-labelledby="w-active">
        <h2 id="w-active">{tw.activeOrders}</h2>
        {active.data && active.data.length > 0 ? (
          <ul className="plain stack">
            {active.data.map((o) => (
              <OrderRow key={o.id} order={o} />
            ))}
          </ul>
        ) : (
          <p className="muted">{tw.noOrders}</p>
        )}
      </section>

      <section className="card stack" aria-labelledby="w-city">
        <h2 id="w-city">{tp.workCity}</h2>
        <ErrorLine message={places.error && tp.loadFailed} />
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            void saveCity()
          }}
        >
          <CityPicker id="w-city-pick" label={tp.workCity} hint={tp.workCityHint} cities={places.cities} value={cityValue} onChange={setCity} hideLegend />
          <div className="actions">
            <button type="submit" disabled={action.busy || !cityValue || city === null}>
              {tp.saveCity}
            </button>
          </div>
        </form>
      </section>

      <section className="card stack" aria-labelledby="w-langs">
        <h2 id="w-langs">{tp.languages}</h2>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            void saveLanguages()
          }}
        >
          <LanguagePicker id="w-langs-pick" languages={places.languages} value={spokenValue} onChange={setSpoken} hideLegend />
          <div className="actions">
            <button type="submit" disabled={action.busy || spoken === null}>
              {tp.saveLanguages}
            </button>
          </div>
        </form>
      </section>

      <section className="card stack" aria-labelledby="w-about">
        <h2 id="w-about">{tw.about}</h2>
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault()
            const result = await action.run(() => workApi.setDescription(about ?? p.description ?? ''))
            if (result) {
              profile.setData(result)
              setAbout(null)
            }
          }}
        >
          <textarea aria-labelledby="w-about" rows={3} maxLength={600} value={about ?? p.description ?? ''} onChange={(e) => setAbout(e.target.value)} />
          <div className="actions">
            <button type="submit" className="button-secondary" disabled={action.busy}>
              {tw.saveAbout}
            </button>
          </div>
        </form>
      </section>
    </section>
  )
}
