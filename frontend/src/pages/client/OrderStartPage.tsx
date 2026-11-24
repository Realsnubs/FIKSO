import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { clientApi } from '../../api/work'
import type { ApiError } from '../../api/client'
import { useAuth } from '../../auth/context'
import { ClientNav } from '../../components/ClientNav'
import { Skeleton } from '../../components/Skeleton'
import { entrySource, findOrderable, localized, usePublicCatalogue } from '../../catalogue/publicCatalogue'
import { errorMessage, t } from '../../i18n/lv'
import { useLanguage } from '../../i18n/LanguageContext'
import { usePageTitle } from '../../i18n/usePageTitle'
import { CityPicker } from '../../work/places'
import { ANY_LANGUAGE, cityName, languageName, usePlaces } from '../../work/placesData'
import { DemoBanner, PriceCard } from './parts'

const to = t.orderStart
const ta = t.app.order
const tp = t.app.places
const tg = t.app.guest

const PHONE = /^\+[1-9]\d{7,14}$/
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type Step = 'describe' | 'where' | 'review'
// Labels are read on render: a language switch replaces the strings after this module was loaded.
const STEPS: { key: Step | 'service'; label: () => string }[] = [
  { key: 'service', label: () => to.stepService },
  { key: 'describe', label: () => to.stepDescribe },
  { key: 'where', label: () => to.stepWhere },
  { key: 'review', label: () => to.stepReview },
]

interface Photo {
  file: File
  url: string
}

/**
 * Order start for one service (R-REQ-01..07, R-WEB-02): the W-ID comes in the URL (`?w=W092`), so it is kept through
 * sign-in, together with `src=web` from the website. Sending creates the request, uploads the photos (re-encoded by
 * the backend, draft only) and submits it; matching then starts automatically (OQ-20). A guest enters name, phone and
 * e-mail on the last step instead of registering: the client account is created just before sending.
 */
export function OrderStartPage() {
  usePageTitle(to.title)
  const [params] = useSearchParams()
  const wId = params.get('w') ?? ''
  const src = entrySource(params)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, startGuest } = useAuth()
  const { language } = useLanguage()
  const { catalogue, loading } = usePublicCatalogue()
  const found = catalogue && wId ? findOrderable(catalogue, wId) : null

  const [step, setStep] = useState<Step>('describe')
  const [description, setDescription] = useState('')
  const [photos, setPhotos] = useState<Photo[]>([])
  const [address, setAddress] = useState('')
  const places = usePlaces()
  const [city, setCity] = useState('')
  const [talk, setTalk] = useState(ANY_LANGUAGE)
  const [details, setDetails] = useState('')
  const [when, setWhen] = useState<'asap' | 'later'>('asap')
  const [time, setTime] = useState('')
  const [hours, setHours] = useState(3)
  const [point, setPoint] = useState<{ lat: string; lon: string } | null>(null)
  const [locating, setLocating] = useState<string | null>(null)
  const [sending, setSending] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  // A failed send (e.g. an upload limit) is resumed on the same draft instead of creating a second request.
  const [draft, setDraft] = useState<{ id: string; uploaded: number } | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [contact, setContact] = useState({ full_name: '', phone: '', email: '' })
  const [accountExists, setAccountExists] = useState(false)
  const photosRef = useRef(photos)
  useEffect(() => {
    photosRef.current = photos
  }, [photos])

  // Previews live in temporary Blob URLs; all are released when the page closes.
  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.url)), [])

  function addPhotos(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []).filter((f) => f.type.startsWith('image/'))
    event.target.value = ''
    setPhotos((prev) => [...prev, ...picked.map((file) => ({ file, url: URL.createObjectURL(file) }))])
  }

  function removePhoto(index: number) {
    setPhotos((prev) => {
      URL.revokeObjectURL(prev[index].url)
      return prev.filter((_, i) => i !== index)
    })
  }

  function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const found: string[] = []
    if (step === 'describe' && !description.trim()) found.push(to.descriptionRequired)
    else if (step === 'describe' && (description.trim().length < 10 || description.trim().length > 2000)) found.push(ta.descriptionLength)
    if (step === 'where') {
      if (!city) found.push(tp.cityRequired)
      if (!address.trim()) found.push(to.addressRequired)
      if (when === 'later' && !time) found.push(to.timeRequired)
    }
    setProblems(found)
    if (found.length > 0) return
    if (step === 'describe') setStep('where')
    else if (step === 'where') setStep('review')
  }

  function locate() {
    if (!navigator.geolocation) {
      setLocating(ta.locationFailed)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPoint({ lat: pos.coords.latitude.toFixed(6), lon: pos.coords.longitude.toFixed(6) })
        setLocating(ta.locationUsed)
      },
      () => setLocating(ta.locationFailed),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  function contactProblems(): string[] {
    const found: string[] = []
    if (!contact.full_name.trim()) found.push(tg.nameRequired)
    if (!PHONE.test(contact.phone.replace(/\s/g, ''))) found.push(tg.phoneInvalid)
    if (!EMAIL.test(contact.email.trim())) found.push(tg.emailInvalid)
    return found
  }

  async function send() {
    if (!found) return
    setSendError(null)
    setAccountExists(false)
    if (!user) {
      const missing = contactProblems()
      setProblems(missing)
      if (missing.length > 0) return
      try {
        setSending(tg.creatingAccount)
        await startGuest({
          full_name: contact.full_name.trim(),
          phone: contact.phone.replace(/\s/g, ''),
          email: contact.email.trim(),
        })
      } catch (error) {
        const code = (error as ApiError).code
        setSending(null)
        if (code === 'EMAIL_TAKEN' || code === 'PHONE_TAKEN') {
          setAccountExists(true)
          setSendError(tg.accountExists)
        } else setSendError(errorMessage(error as ApiError))
        return
      }
    }
    let from: Date | null = null
    if (when === 'later') from = new Date(time)
    try {
      setSending(ta.sending)
      const created =
        draft ??
        (await clientApi
          .create({
            w_id: found.service.wId,
            description: description.trim(),
            request_type: when === 'later' ? 'reserved' : 'immediate',
            preferred_time_from: from ? from.toISOString() : undefined,
            preferred_time_to: from ? new Date(from.getTime() + hours * 3600_000).toISOString() : undefined,
            address: address.trim(),
            flat: details.trim() || undefined,
            lat: point?.lat,
            lon: point?.lon,
            city,
            communication_language: talk,
            src,
          })
          .then((r) => ({ id: r.id, uploaded: 0 })))
      setDraft(created)
      for (let i = created.uploaded; i < photos.length; i++) {
        setSending(ta.uploading(i + 1, photos.length))
        await clientApi.addPhoto(created.id, photos[i].file)
        setDraft({ id: created.id, uploaded: i + 1 })
      }
      setSending(ta.sending)
      await clientApi.submit(created.id)
      navigate(`/client/pieteikumi/${created.id}`, { replace: true })
    } catch (error) {
      setSending(null)
      setSendError(errorMessage(error as ApiError))
    }
  }

  if (loading) return <Skeleton variant="page" />
  if (!found) {
    // Unknown, disabled or not yet orderable W-ID: a neutral start (R-WEB-02 AC).
    return (
      <section>
        <ClientNav />
        <h1>{to.title}</h1>
        <p className="notice">{to.unknownService}</p>
        <div className="actions">
          <Link to="/pakalpojumi" className="link-button">
            {t.client.browse}
          </Link>
        </div>
      </section>
    )
  }

  const { spec, category, service } = found
  const current = STEPS.findIndex((s) => s.key === step)
  return (
    <section>
      <ClientNav />
      {catalogue?.demo && <DemoBanner />}
      <Link to={`/pakalpojumi/${spec.id}`} className="back-link">
        <span aria-hidden="true">←</span> {to.back}
      </Link>
      <h1>{to.title}</h1>
      <ol className="stepper" aria-label={to.steps}>
        {STEPS.map((s, i) => (
          <li key={s.key} className={i < current ? 'done' : i === current ? 'now' : undefined} aria-current={i === current ? 'step' : undefined}>
            <span className="n" aria-hidden="true">
              {i < current ? '✓' : i + 1}
            </span>
            {s.label()}
          </li>
        ))}
      </ol>
      <div className="order-layout">
        <form className="stack" onSubmit={next} noValidate>
          <div className="chosen">
            <strong>{to.chosen(service.wId, localized(service.name, language))}</strong>
            <span className="path">
              {localized(category.name, language)} → {localized(spec.name, language)}
            </span>
            <Link to={`/pakalpojumi/${spec.id}`}>{to.change}</Link>
          </div>

          {step === 'describe' && (
            <>
              <div className="field">
                <label htmlFor="o-desc">{to.description}</label>
                <textarea
                  id="o-desc"
                  rows={5}
                  value={description}
                  aria-describedby="o-desc-hint"
                  aria-invalid={problems.includes(to.descriptionRequired) || undefined}
                  onChange={(e) => setDescription(e.target.value)}
                />
                <small id="o-desc-hint" className="hint">
                  {to.descriptionHint}
                </small>
              </div>
              <div className="field">
                <label htmlFor="o-photos">{to.photos}</label>
                <input id="o-photos" type="file" accept="image/*" multiple onChange={addPhotos} aria-describedby="o-photos-hint" />
                <small id="o-photos-hint" className="hint">
                  {to.photosHint}
                </small>
                {photos.length > 0 && (
                  <ul className="thumbs" aria-label={to.photoCount(photos.length)}>
                    {photos.map((p, i) => (
                      <li key={p.url}>
                        <img src={p.url} alt="" />
                        <button type="button" className="button-secondary" aria-label={to.removePhoto(i + 1)} onClick={() => removePhoto(i)}>
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}

          {step === 'where' && (
            <>
              {places.error && <p className="error">{tp.loadFailed}</p>}
              <CityPicker
                id="o-city"
                label={tp.city}
                hint={tp.cityHint}
                cities={places.cities}
                value={city}
                onChange={setCity}
                invalid={problems.includes(tp.cityRequired)}
              />
              <div className="field">
                <label htmlFor="o-address">{to.address}</label>
                <input
                  id="o-address"
                  value={address}
                  autoComplete="street-address"
                  aria-describedby="o-address-hint"
                  aria-invalid={problems.includes(to.addressRequired) || undefined}
                  onChange={(e) => setAddress(e.target.value)}
                />
                <small id="o-address-hint" className="hint">
                  {to.addressHint}
                </small>
              </div>
              <div className="actions">
                <button type="button" className="button-secondary button-small" onClick={locate}>
                  {ta.useLocation}
                </button>
                {locating && (
                  <span className="hint" role="status">
                    {locating}
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="o-details">{to.addressDetails}</label>
                <input id="o-details" value={details} onChange={(e) => setDetails(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="o-talk">{tp.clientLanguage}</label>
                <select id="o-talk" value={talk} aria-describedby="o-talk-hint" onChange={(e) => setTalk(e.target.value)}>
                  <option value={ANY_LANGUAGE}>{tp.anyLanguage}</option>
                  {places.languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {languageName(l.code, places.languages, language)}
                      {l.native_name !== l.name[language] ? ` (${l.native_name})` : ''}
                    </option>
                  ))}
                </select>
                <small id="o-talk-hint" className="hint">
                  {tp.clientLanguageHint}
                </small>
              </div>
              <fieldset className="field">
                <legend>{to.when}</legend>
                <div className="choice-row">
                  <label className={when === 'asap' ? 'on' : undefined}>
                    <input type="radio" name="o-when" checked={when === 'asap'} onChange={() => setWhen('asap')} /> {to.asap}
                  </label>
                  <label className={when === 'later' ? 'on' : undefined}>
                    <input type="radio" name="o-when" checked={when === 'later'} onChange={() => setWhen('later')} /> {to.later}
                  </label>
                </div>
              </fieldset>
              {when === 'later' && (
                <div className="field">
                  <label htmlFor="o-time">{to.dateTime}</label>
                  <input
                    id="o-time"
                    type="datetime-local"
                    value={time}
                    aria-invalid={problems.includes(to.timeRequired) || undefined}
                    onChange={(e) => setTime(e.target.value)}
                  />
                  <label htmlFor="o-hours">{ta.duration}</label>
                  <select id="o-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                    {[2, 3, 4, 6, 8].map((h) => (
                      <option key={h} value={h}>
                        {ta.hours(h)}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}

          {step === 'review' && (
            <section className="card stack" aria-labelledby="o-review">
              <h2 id="o-review">{to.reviewTitle}</h2>
              <dl className="summary-list">
                <dt>{to.stepService}</dt>
                <dd>
                  <code>{service.wId}</code> {localized(service.name, language)}
                </dd>
                <dt>{to.description}</dt>
                <dd>{description}</dd>
                <dt>{to.photos}</dt>
                <dd>{to.photoCount(photos.length)}</dd>
                <dt>{tp.city}</dt>
                <dd>{cityName(places.cities.find((c) => c.code === city), language)}</dd>
                <dt>{to.address}</dt>
                <dd>
                  {address}
                  {details && ` · ${details}`}
                </dd>
                <dt>{tp.communicationLanguage}</dt>
                <dd>{languageName(talk, places.languages, language)}</dd>
                <dt>{to.when}</dt>
                <dd>{when === 'asap' ? to.asap : time.replace('T', ' ')}</dd>
              </dl>
              {!user && (
                <fieldset className="stack" aria-describedby="o-contacts-hint">
                  <legend>{tg.contacts}</legend>
                  <small id="o-contacts-hint" className="hint">
                    {tg.contactsHint}
                  </small>
                  <div className="field">
                    <label htmlFor="o-name">{t.register.fullName}</label>
                    <input
                      id="o-name"
                      value={contact.full_name}
                      autoComplete="name"
                      maxLength={120}
                      aria-invalid={problems.includes(tg.nameRequired) || undefined}
                      onChange={(e) => setContact({ ...contact, full_name: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="o-phone">{t.register.phone}</label>
                    <input
                      id="o-phone"
                      type="tel"
                      value={contact.phone}
                      autoComplete="tel"
                      placeholder="+371"
                      aria-describedby="o-phone-hint"
                      aria-invalid={problems.includes(tg.phoneInvalid) || undefined}
                      onChange={(e) => setContact({ ...contact, phone: e.target.value })}
                    />
                    <small id="o-phone-hint" className="hint">
                      {tg.phoneHint}
                    </small>
                  </div>
                  <div className="field">
                    <label htmlFor="o-email">{t.login.email}</label>
                    <input
                      id="o-email"
                      type="email"
                      value={contact.email}
                      autoComplete="email"
                      aria-describedby="o-email-hint"
                      aria-invalid={problems.includes(tg.emailInvalid) || undefined}
                      onChange={(e) => setContact({ ...contact, email: e.target.value })}
                    />
                    <small id="o-email-hint" className="hint">
                      {tg.emailHint}
                    </small>
                  </div>
                  <p>
                    {tg.haveAccount}{' '}
                    <Link to={`/login?returnTo=${encodeURIComponent(location.pathname + location.search)}`}>{tg.login}</Link>
                  </p>
                </fieldset>
              )}
              <p className="muted">{to.afterSend}</p>
              {catalogue?.demo && (
                <p className="notice" id="o-send-note">
                  {to.sendUnavailable}
                </p>
              )}
              {sending && (
                <p className="hint" role="status">
                  {sending}
                </p>
              )}
              {sendError && (
                <p className="error" role="alert">
                  {sendError}{' '}
                  {accountExists && (
                    <Link to={`/login?returnTo=${encodeURIComponent(location.pathname + location.search)}`}>{tg.login}</Link>
                  )}
                </p>
              )}
            </section>
          )}

          {problems.length > 0 && (
            <ul role="alert" className="error plain">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}

          <div className="actions">
            {step !== 'describe' && (
              <button type="button" className="button-secondary" onClick={() => (setProblems([]), setStep(step === 'review' ? 'where' : 'describe'))}>
                {to.prev}
              </button>
            )}
            {step === 'review' ? (
              <button
                type="button"
                disabled={Boolean(catalogue?.demo) || sending !== null}
                aria-busy={sending !== null || undefined}
                aria-describedby={catalogue?.demo ? 'o-send-note' : undefined}
                onClick={send}
              >
                {to.send}
              </button>
            ) : (
              <button type="submit">{to.next}</button>
            )}
          </div>
        </form>
        <aside>
          <PriceCard />
        </aside>
      </div>
    </section>
  )
}
