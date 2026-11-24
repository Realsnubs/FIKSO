import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { AuthContext, type AuthState } from '../auth/context'
import { applyLanguage } from '../i18n/language'
import { ApiError } from '../api/client'
import type { GuestPayload, Role, User } from '../types/api'
import type { ClientRequest, MasterOrder } from '../types/work'
import { resetPlaces } from '../work/placesData'

function user(role: Role): User {
  return {
    id: 'u1', role, email: 'x@example.lv', full_name: 'Laura Kalniņa', phone: '+37120000002', status: 'active',
    master_approval_status: role === 'master' ? 'approved' : null, has_password: true, created_at: '2026-10-01T09:00:00Z',
  }
}

function auth(current: User | null): AuthState {
  const noop = async () => {
    throw new Error('not used')
  }
  return { user: current, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

type Handler = (init?: RequestInit) => unknown
/** A fetch stub that answers by "METHOD path"; records every call. */
function api(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown; headers: Record<string, string> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      const key = `${init?.method ?? 'GET'} ${url.pathname.replace('/api/v1', '')}`
      calls.push({
        key,
        body: init?.body && typeof init.body === 'string' ? JSON.parse(init.body) : init?.body,
        headers: (init?.headers ?? {}) as Record<string, string>,
      })
      const handler = Object.entries({ ...PLACES, ...routes }).find(([pattern]) => new RegExp(`^${pattern}$`).test(key))?.[1]
      if (!handler) return new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'x' } }), { status: 404 })
      const body = handler(init)
      return new Response(body === undefined ? null : JSON.stringify(body), { status: body === undefined ? 204 : 200 })
    }),
  )
  return calls
}

function renderAt(path: string, current: User | null) {
  render(
    <AuthContext.Provider value={auth(current)}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetPlaces()
  applyLanguage('lv')
})

const CITIES = [
  { code: 'riga', name: { lv: 'Rīga', en: 'Riga', ru: 'Рига' } },
  { code: 'rezekne', name: { lv: 'Rēzekne', en: 'Rēzekne', ru: 'Резекне' } },
  { code: 'jelgava', name: { lv: 'Jelgava', en: 'Jelgava', ru: 'Елгава' } },
]
const LANGUAGES = [
  { code: 'lv', name: { lv: 'Latviešu', en: 'Latvian', ru: 'Латышский' }, native_name: 'Latviešu', flag: '🇱🇻' },
  { code: 'ru', name: { lv: 'Krievu', en: 'Russian', ru: 'Русский' }, native_name: 'Русский', flag: '🇷🇺' },
  { code: 'uk', name: { lv: 'Ukraiņu', en: 'Ukrainian', ru: 'Украинский' }, native_name: 'Українська', flag: '🇺🇦' },
]
// Reference lists every page with a city or a language loads; a test route of the same key wins.
const PLACES: Record<string, Handler> = {
  'GET /public/cities': () => CITIES,
  'GET /public/communication-languages': () => LANGUAGES,
}

const CATALOGUE = {
  computed_at: '2026-11-05T10:00:00Z',
  categories: [
    {
      id: 'c1',
      name: { lv: 'Mazā santehnika' },
      specialisations: [
        {
          id: 's1', slug: 'gaismeklu-meistars', name: { lv: 'Gaismekļu meistars', en: 'Light fitter' }, description: null, lead: null,
          status: 'active', card_image: null,
          services: [{ id: 'sv1', w_id: 'W092', name: { lv: 'Gaismekļa uzstādīšana' }, description: null }],
        },
        { id: 's2', slug: 'logu-meistars', name: { lv: 'Logu meistars' }, description: null, lead: null, status: 'planned', card_image: null, services: [] },
      ],
    },
  ],
}
const TERMS = { hourly_rate_eur: '40.00', minimum_order_eur: '40.00', materials_note: 'Materiāli un palīgmateriāli tiek apmaksāti atsevišķi.', materials_note_lang: 'lv' }

function request(over: Partial<ClientRequest> = {}): ClientRequest {
  return {
    id: 'r1', status: 'proposed', unserved_reason: null,
    service: { id: 'sv1', w_id: 'W092', name: 'Gaismekļa uzstādīšana', specialisation: 'Gaismekļu meistars', category: 'Mazā santehnika' },
    description: 'Jāuzstāda griestu lustra.', request_type: 'immediate', preferred_time_from: null, preferred_time_to: null,
    address: 'Brīvības iela 1, Rīga', flat: null, access_info: null, geocode_source: 'stub', source: 'website_deeplink',
    city: CITIES[0], communication_language: 'any',
    current_round: 1, photos: [], created_at: '2026-11-05T10:00:00Z', submitted_at: '2026-11-05T10:00:00Z', cancelled_at: null, version: 3,
    proposal: {
      round: 1,
      expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
      masters: [
        { candidate_id: 'cand1', role: 'proposal', first_name: 'Jānis', description: 'Elektriķis', rating_avg: '4.80', rating_count: 12, completed_jobs: 40, eta_minutes: 18, distance_km: '4.20' },
        { candidate_id: 'cand2', role: 'alternative', first_name: 'Pēteris', description: null, rating_avg: null, rating_count: 0, completed_jobs: 0, eta_minutes: 25, distance_km: '7.00' },
      ],
    },
    order: null,
    ...over,
  }
}

function masterOrder(over: Partial<MasterOrder> = {}): MasterOrder {
  return {
    id: 'o1', status: 'offered', order_type: 'immediate',
    service: { id: 'sv1', w_id: 'W092', name: 'Gaismekļa uzstādīšana', specialisation: 'Gaismekļu meistars', category: 'Mazā santehnika' },
    description: 'Jāuzstāda griestu lustra.', photos: [], estimated_start: '2026-11-05T10:20:00Z', scheduled_start: null, scheduled_end: null,
    offer_expires_at: new Date(Date.now() + 10 * 60_000).toISOString(), city: CITIES[0], communication_language: 'ru',
    client: null, address: null,
    timeline: { offered_at: '2026-11-05T10:00:00Z', accepted_at: null, en_route_at: null, arrived_at: null, work_started_at: null, work_completed_at: null, completed_at: null },
    work_running: false, billable_seconds: 0, terms: { hourly_rate_eur: '40.00', minimum_order_eur: '40.00', commission_rate: '0.2500' }, worksheet: null,
    ...over,
  }
}

describe('public catalogue from the API', () => {
  it('shows only what the API returns: orderable services and "Drīzumā", page addresses by slug', async () => {
    const calls = api({ 'GET /public/catalogue': () => CATALOGUE, 'GET /public/commercial-terms': () => TERMS, 'POST /public/events': () => undefined })
    renderAt('/pakalpojumi', null)
    const grid = await screen.findByRole('list', { name: 'Pakalpojumi' })
    const link = within(grid).getAllByRole('link')[0]
    expect(link.getAttribute('href')).toBe('/pakalpojumi/gaismeklu-meistars')
    expect(within(screen.getByRole('list', { name: 'Drīzumā' })).getByText('Logu meistars')).toBeTruthy()
    await waitFor(() => expect(calls.some((c) => c.key === 'POST /public/events')).toBe(true))
  })
})

describe('client request flow', () => {
  it('sends the request with the W-ID and src=web, uploads nothing extra and opens the request', async () => {
    const calls = api({
      'GET /public/catalogue': () => CATALOGUE,
      'GET /public/commercial-terms': () => TERMS,
      'POST /client/requests': () => request({ status: 'draft', proposal: null }),
      'POST /client/requests/r1/submit': () => request(),
      'GET /client/requests/r1': () => request(),
    })
    renderAt('/pieteikums/jauns?w=W092&src=web', user('client'))
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Rīga' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Brīvības iela 1, Rīga')
    await userEvent.selectOptions(screen.getByLabelText('Valoda saziņai'), 'ru')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByText('🇷🇺 Krievu')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    expect(await screen.findByRole('heading', { name: 'FIKSO iesaka šo meistaru' })).toBeTruthy()
    const create = calls.find((c) => c.key === 'POST /client/requests')
    expect(create?.body).toMatchObject({
      w_id: 'W092', src: 'web', request_type: 'immediate', address: 'Brīvības iela 1, Rīga', city: 'riga', communication_language: 'ru',
    })
    expect(calls.some((c) => c.key === 'POST /client/requests/r1/submit')).toBe(true)
  })

  it('a failed photo upload is resumed on the same draft, never a second request (browser QA regression)', async () => {
    let uploads = 0
    const calls: { key: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string, init?: RequestInit) => {
        const key = `${init?.method ?? 'GET'} ${new URL(input, 'http://localhost').pathname.replace('/api/v1', '')}`
        calls.push({ key })
        const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
        if (key === 'GET /public/catalogue') return json(CATALOGUE)
        if (key === 'GET /public/commercial-terms') return json(TERMS)
        if (key === 'GET /public/cities') return json(CITIES)
        if (key === 'GET /public/communication-languages') return json(LANGUAGES)
        if (key === 'POST /client/requests') return json(request({ status: 'draft', proposal: null }))
        if (key === 'POST /client/requests/r1/photos') {
          uploads += 1
          return uploads === 1
            ? json({ error: { code: 'RATE_LIMITED', message: 'x' } }, 429)
            : json({ id: `p${uploads}`, size_bytes: 1, uploaded_at: '2026-11-05T10:00:00Z' })
        }
        if (key === 'POST /client/requests/r1/submit' || key === 'GET /client/requests/r1') return json(request())
        return json({ error: { code: 'NOT_FOUND', message: 'x' } }, 404)
      }),
    )
    renderAt('/pieteikums/jauns?w=W092', user('client'))
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.upload(screen.getByLabelText('Foto'), new File(['x'], 'a.jpg', { type: 'image/jpeg' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Rīga' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Brīvības iela 1, Rīga')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    expect(await screen.findByText('Pārāk daudz mēģinājumu. Mēģiniet vēlāk.')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    expect(await screen.findByRole('heading', { name: 'FIKSO iesaka šo meistaru' })).toBeTruthy()
    expect(calls.filter((c) => c.key === 'POST /client/requests')).toHaveLength(1)
    expect(uploads).toBe(2)
  })

  it('a guest orders without registering: contacts on the last step, account first, then the request', async () => {
    const calls = api({
      'GET /public/catalogue': () => CATALOGUE,
      'GET /public/commercial-terms': () => TERMS,
      'POST /client/requests': () => request({ status: 'draft', proposal: null }),
      'POST /client/requests/r1/submit': () => request(),
      'GET /client/requests/r1': () => request(),
    })
    const startGuest = vi.fn<(data: GuestPayload) => Promise<User>>(async () => user('client'))
    function Guest() {
      const [current, setCurrent] = useState<User | null>(null)
      const state = { ...auth(current), startGuest: async (data: GuestPayload) => setCurrent(await startGuest(data)) as never }
      return (
        <AuthContext.Provider value={state}>
          <MemoryRouter initialEntries={['/pieteikums/jauns?w=W092']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext.Provider>
      )
    }
    render(<Guest />)
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Rīga' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Brīvības iela 1, Rīga')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByRole('group', { name: 'Tavi kontakti' })).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    expect(screen.getByText('Ievadi vārdu.')).toBeTruthy()
    expect(startGuest).not.toHaveBeenCalled()
    await userEvent.type(screen.getByLabelText('Vārds, uzvārds'), 'Anna Ozola')
    await userEvent.type(screen.getByLabelText('Tālrunis'), '+371 2000 0003')
    await userEvent.type(screen.getByLabelText('E-pasts'), 'anna@example.lv')
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    expect(await screen.findByRole('heading', { name: 'FIKSO iesaka šo meistaru' })).toBeTruthy()
    expect(startGuest).toHaveBeenCalledWith({ full_name: 'Anna Ozola', phone: '+37120000003', email: 'anna@example.lv' })
    expect(calls.filter((c) => c.key === 'POST /client/requests')).toHaveLength(1)
  })

  it('a guest whose e-mail already has an account is asked to sign in; nothing is sent', async () => {
    const calls = api({ 'GET /public/catalogue': () => CATALOGUE, 'GET /public/commercial-terms': () => TERMS })
    const state = {
      ...auth(null),
      startGuest: async () => {
        throw new ApiError(409, 'EMAIL_TAKEN', 'x')
      },
    }
    render(
      <AuthContext.Provider value={state}>
        <MemoryRouter initialEntries={['/pieteikums/jauns?w=W092']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthContext.Provider>,
    )
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Rīga' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Brīvības iela 1, Rīga')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.type(screen.getByLabelText('Vārds, uzvārds'), 'Anna Ozola')
    await userEvent.type(screen.getByLabelText('Tālrunis'), '+37120000003')
    await userEvent.type(screen.getByLabelText('E-pasts'), 'anna@example.lv')
    await userEvent.click(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' }))
    const alert = await screen.findByText(/Ar šiem kontaktiem konts jau ir/)
    const login = within(alert).getByRole('link', { name: 'Pieslēgties' })
    expect(decodeURIComponent(login.getAttribute('href') ?? '')).toBe('/login?returnTo=/pieteikums/jauns?w=W092')
    expect(calls.some((c) => c.key === 'POST /client/requests')).toBe(false)
  })

  it('a master who opens the order link is sent to their own area', async () => {
    api({ 'GET /public/catalogue': () => CATALOGUE, 'GET /public/commercial-terms': () => TERMS })
    renderAt('/pieteikums/jauns?w=W092', user('master'))
    expect(await screen.findByRole('heading', { level: 1, name: 'Meistara panelis' })).toBeTruthy()
  })

  it('a client without a password is offered to set one; a client with one is not', async () => {
    const setPassword = vi.fn(async () => user('client'))
    api({ 'GET /client/requests/r1': () => request() })
    render(
      <AuthContext.Provider value={{ ...auth({ ...user('client'), has_password: false }), setPassword }}>
        <MemoryRouter initialEntries={['/client/pieteikumi/r1']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthContext.Provider>,
    )
    expect(await screen.findByRole('heading', { name: 'Iestati paroli' })).toBeTruthy()
    await userEvent.type(screen.getByLabelText('Jaunā parole'), 'garā-parole-123')
    await userEvent.click(screen.getByRole('button', { name: 'Saglabāt paroli' }))
    expect(await screen.findByText('Parole saglabāta.')).toBeTruthy()
    expect(setPassword).toHaveBeenCalledWith('garā-parole-123')
  })

  it('a client who has a password sees no password card', async () => {
    api({ 'GET /client/requests/r1': () => request() })
    renderAt('/client/pieteikumi/r1', user('client'))
    expect(await screen.findByRole('heading', { name: 'FIKSO iesaka šo meistaru' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Iestati paroli' })).toBeNull()
  })

  it('a too short description is stopped before anything is sent', async () => {
    const calls = api({ 'GET /public/catalogue': () => CATALOGUE, 'GET /public/commercial-terms': () => TERMS })
    renderAt('/pieteikums/jauns?w=W092', user('client'))
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Lustra')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByRole('alert').textContent).toContain('no 10 līdz 2000')
    expect(calls.filter((c) => c.key.startsWith('POST /client'))).toEqual([])
  })

  it('the city is required and found by its name without diacritics; the default language is "any"', async () => {
    const calls = api({ 'GET /public/catalogue': () => CATALOGUE, 'GET /public/commercial-terms': () => TERMS })
    renderAt('/pieteikums/jauns?w=W092', user('client'))
    await userEvent.type(await screen.findByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Atbrīvošanas aleja 1')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByRole('alert').textContent).toContain('Izvēlies pilsētu.')
    expect((screen.getByLabelText('Valoda saziņai') as HTMLSelectElement).value).toBe('any')
    await userEvent.type(screen.getByLabelText('Meklēt pilsētu'), 'rezekne')
    expect(screen.queryByRole('radio', { name: 'Rīga' })).toBeNull()
    await userEvent.click(screen.getByRole('radio', { name: 'Rēzekne' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByText('Jebkura pieejamā valoda')).toBeTruthy()
    expect(calls.filter((c) => c.key.startsWith('POST /client'))).toEqual([])
  })

  it('the request page shows the city and the communication language', async () => {
    api({ 'GET /client/requests/r1': () => request({ communication_language: 'uk' }) })
    renderAt('/client/pieteikumi/r1', user('client'))
    expect(await screen.findByText('🇺🇦 Ukraiņu')).toBeTruthy()
    expect(screen.getByText('Rīga')).toBeTruthy()
  })

  it('the proposal shows the master without contacts, a timer, and confirms the chosen one', async () => {
    const calls = api({
      'GET /client/requests/r1': () => request(),
      'POST /client/requests/r1/confirm': () =>
        request({ status: 'confirmed', proposal: null, order: { ...masterSummary(), status: 'offered', master_phone: null } }),
    })
    renderAt('/client/pieteikumi/r1', user('client'))
    expect(await screen.findByText('Jānis')).toBeTruthy()
    expect(screen.getByRole('timer').textContent).toMatch(/Apstiprini \d:\d\d laikā/)
    expect(screen.queryByText(/\+371/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Izvēlēties šo' }))
    await waitFor(() => expect(calls.find((c) => c.key === 'POST /client/requests/r1/confirm')?.body).toEqual({ candidate_id: 'cand2' }))
    expect(await screen.findByText('Piedāvājums nosūtīts meistaram. Tiklīdz viņš atbildēs, redzēsi šeit.')).toBeTruthy()
  })

  it('a completed order shows the summary with labour, materials and the payment note', async () => {
    api({
      'GET /client/requests/r1': () =>
        request({ status: 'confirmed', proposal: null, order: { ...masterSummary(), status: 'completed', labour_amount_eur: '40.00', materials_amount_eur: '15.00', billable_minutes: 30, completed_at: '2026-11-05T12:00:00Z' } }),
    })
    renderAt('/client/pieteikumi/r1', user('client'))
    expect(await screen.findByText('40,00 €')).toBeTruthy()
    expect(screen.getByText('15,00 €')).toBeTruthy()
    expect(screen.getByText('Samaksu veic tieši meistaram. Materiāli tiek apmaksāti atsevišķi.')).toBeTruthy()
  })
})

function masterSummary() {
  return {
    id: 'o1', status: 'accepted' as const, master_name: 'Jānis', master_phone: '+37120000001', offered_at: '2026-11-05T10:00:00Z',
    accepted_at: '2026-11-05T10:01:00Z', en_route_at: null, arrived_at: null, work_started_at: null, work_completed_at: null,
    completed_at: null, estimated_start: '2026-11-05T10:20:00Z', scheduled_start: null, scheduled_end: null, master_location: null,
    labour_amount_eur: null, materials_amount_eur: null, billable_minutes: null, work_description: null, review_rating: null,
  }
}

const PROFILE = {
  approval_status: 'approved', availability_mode: 'available_for_reservations', is_busy: false, description: null,
  work_city: 'riga', languages: ['lv', 'ru'], location_updated_at: null, location_fresh: false, location_interval_seconds: 180,
  rating_avg: null, rating_count: 0, completed_jobs: 0, commission_balance_eur: '0.00', commission_limit_eur: '100.00', commission_limit_reached: false,
}

describe('master work', () => {
  it('an offer shows the job without address or phone, a timer, and can be accepted', async () => {
    const calls = api({
      'GET /master/work-profile': () => PROFILE,
      'GET /master/offers': () => [masterOrder()],
      'GET /master/orders': () => [],
      'POST /master/orders/o1/accept': () => masterOrder({ status: 'accepted' }),
    })
    renderAt('/master/darbs', user('master'))
    expect(await screen.findByText('Jāuzstāda griestu lustra.')).toBeTruthy()
    expect(screen.getByRole('timer').textContent).toMatch(/Atbildi \d+:\d\d laikā/)
    expect(screen.queryByText(/Brīvības/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Pieņemt' }))
    await waitFor(() => expect(calls.some((c) => c.key === 'POST /master/orders/o1/accept')).toBe(true))
  })

  it('the work city and the languages are chosen from searchable lists; there is no zone or location button', async () => {
    const calls = api({
      'GET /master/work-profile': () => ({ ...PROFILE, work_city: null, languages: [] }),
      'GET /master/offers': () => [],
      'GET /master/orders': () => [],
      'PUT /master/work-city': () => ({ ...PROFILE, languages: [] }),
      'PUT /master/languages': () => ({ ...PROFILE, languages: ['ru', 'uk'] }),
    })
    renderAt('/master/darbs', user('master'))
    expect(await screen.findByText('Izvēlies darba pilsētu — bez tās piedāvājumi netiek sūtīti.')).toBeTruthy()
    expect(screen.getByText('Izvēlies vismaz vienu saziņas valodu — bez tās piedāvājumi netiek sūtīti.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Izmantot manu atrašanās vietu' })).toBeNull()
    expect(screen.queryByLabelText('Rādiuss, km')).toBeNull()
    await userEvent.type(screen.getByLabelText('Meklēt pilsētu'), 'Рига')
    await userEvent.click(screen.getByRole('radio', { name: 'Rīga' }))
    await userEvent.click(screen.getByRole('button', { name: 'Saglabāt pilsētu' }))
    await waitFor(() => expect(calls.find((c) => c.key === 'PUT /master/work-city')?.body).toEqual({ city: 'riga' }))
    await userEvent.type(screen.getByLabelText('Meklēt valodu'), 'укр')
    await userEvent.click(screen.getByRole('checkbox', { name: /Ukraiņu/ }))
    await userEvent.clear(screen.getByLabelText('Meklēt valodu'))
    await userEvent.click(screen.getByRole('checkbox', { name: /Krievu/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Saglabāt valodas' }))
    await waitFor(() => expect(calls.find((c) => c.key === 'PUT /master/languages')?.body).toEqual({ languages: ['uk', 'ru'] }))
    expect(await screen.findByRole('button', { name: 'Noņemt: 🇺🇦 Ukraiņu' })).toBeTruthy()
  })

  it("an offer shows the city and the client's communication language", async () => {
    api({ 'GET /master/work-profile': () => PROFILE, 'GET /master/offers': () => [masterOrder()], 'GET /master/orders': () => [] })
    renderAt('/master/darbs', user('master'))
    expect(await screen.findByText(/Saziņas valoda: 🇷🇺 Krievu/)).toBeTruthy()
    expect(screen.getByText(/· Rīga$/)).toBeTruthy()
  })

  it('the commission page shows the amount due to the FIKSO owner and the entries', async () => {
    api({
      'GET /master/commission': () => ({
        charged_total_eur: '30.00', paid_total_eur: '10.00', adjustments_total_eur: '0.00', balance_eur: '20.00', amount_due_eur: '20.00',
        limit_eur: '100.00', limit_reached: false,
        entries: [
          { id: 'e1', type: 'charge', order_id: 'o1', base_labour_eur: '40.00', amount_eur: '10.00', payment_method: null, paid_on: null, comment: null, created_at: '2026-11-05T12:00:00Z' },
          { id: 'e2', type: 'payment', order_id: null, base_labour_eur: null, amount_eur: '-10.00', payment_method: 'bank_transfer', paid_on: '2026-11-05', comment: 'Pārskaitījums', created_at: '2026-11-05T13:00:00Z' },
        ],
      }),
    })
    renderAt('/master/komisija', user('master'))
    expect(await screen.findByText('Jāapmaksā FIKSO īpašniekam')).toBeTruthy()
    expect(screen.getAllByText('20,00 €').length).toBeGreaterThan(0)
    expect(screen.getByText(/Aprēķins par pasūtījumu/)).toBeTruthy()
    expect(screen.getByText(/Maksājums · Pārskaitījums/)).toBeTruthy()
  })

  it('an accepted order shows the client and address and offers the next step', async () => {
    api({
      'GET /master/orders/o1': () =>
        masterOrder({ status: 'accepted', client: { name: 'Laura', phone: '+37120000002' }, address: { address: 'Brīvības iela 1, Rīga', flat: '5', access_info: null, lat: 56.95, lon: 24.1 } }),
    })
    renderAt('/master/pasutijumi/o1', user('master'))
    expect(await screen.findByText(/Brīvības iela 1, Rīga/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Izbraucu' })).toBeTruthy()
  })
})

describe('admin commission', () => {
  it('records a payment with amount, date, method and comment', async () => {
    const detail = { master_id: 'm1', name: 'Jānis', charged_total_eur: '10.00', paid_total_eur: '0.00', adjustments_total_eur: '0.00', balance_eur: '10.00', limit_eur: '100.00', limit_reached: false, entries: [] }
    const calls = api({
      'GET /admin/commission/masters/m1': () => detail,
      'POST /admin/commission/masters/m1/payments': () => ({ ...detail, paid_total_eur: '10.00', balance_eur: '0.00' }),
    })
    renderAt('/admin/commission/m1', user('admin'))
    await userEvent.type((await screen.findAllByLabelText('Summa, €'))[0], '10')
    await userEvent.type(screen.getByLabelText('Komentārs'), 'Skaidrā')
    await userEvent.click(screen.getAllByRole('button', { name: 'Reģistrēt maksājumu' })[0])
    await waitFor(() => {
      const body = calls.find((c) => c.key === 'POST /admin/commission/masters/m1/payments')?.body as Record<string, string>
      expect(body).toMatchObject({ amount_eur: '10.00', payment_method: 'bank_transfer', comment: 'Skaidrā' })
      expect(body.paid_on).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })
    // A retry of the same submission is booked once by the backend (Idempotency-Key).
    const sent = calls.find((c) => c.key === 'POST /admin/commission/masters/m1/payments')
    expect(sent?.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
  })
})
