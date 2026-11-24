import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../App'
import { AuthContext, type AuthState } from '../../auth/context'
import { applyLanguage } from '../../i18n/language'
import type { User } from '../../types/api'
import { resetPlaces } from '../../work/placesData'

const client: User = {
  id: 'c1',
  role: 'client',
  email: 'laura@example.lv',
  full_name: 'Laura Kalniņa',
  phone: '+37120000002',
  status: 'active',
  master_approval_status: null,
  has_password: true,
  created_at: '2026-10-01T09:00:00Z',
}

function auth(user: User | null): AuthState {
  const noop = async () => {
    throw new Error('not used')
  }
  return { user, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

function renderAt(path: string, user: User | null = null) {
  // Typed like fetch, so the test can look at each call's method.
  // Only the public city and language lists are answered (reference data the order form needs); nothing else exists.
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async (input) => {
    const url = String(input)
    if (url.endsWith('/public/cities')) return new Response(JSON.stringify([{ code: 'riga', name: { lv: 'Rīga', en: 'Riga', ru: 'Рига' } }]))
    if (url.endsWith('/public/communication-languages')) return new Response('[]')
    return new Response('{}', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <AuthContext.Provider value={auth(user)}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return fetchMock
}

const demo = () => vi.stubEnv('VITE_CATALOGUE_DEMO', 'true')

afterEach(() => {
  resetPlaces()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  applyLanguage('lv')
})

describe('client catalogue without a public API (the real app today)', () => {
  it('says honestly that the catalogue is not published, and offers nothing to order', async () => {
    renderAt('/pakalpojumi')
    expect(await screen.findByRole('heading', { name: 'Pakalpojumu katalogs vēl nav publicēts' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Uzzināt vairāk/ })).toBeNull()
    expect(screen.queryByText(/Demonstrācija/)).toBeNull()
    expect(screen.getByText('40 €/h')).toBeTruthy()
  })

  it('a guest at "/" starts in the catalogue', async () => {
    renderAt('/')
    expect(await screen.findByRole('heading', { level: 1, name: 'Kādu darbu vajag paveikt?' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Pieslēgties' })).toBeTruthy()
  })

  it('a deep link to a service gives the neutral start, not a broken form', async () => {
    renderAt('/pieteikums/jauns?w=W092', client)
    expect(await screen.findByText('Šo pakalpojumu pašlaik nevar pasūtīt. Izvēlies pakalpojumu katalogā.')).toBeTruthy()
    expect(screen.queryByLabelText('Ko vajag izdarīt?')).toBeNull()
  })
})

describe('client catalogue with the demo layer', () => {
  it('is marked as a demo and lists only specialisations with orderable services; planned ones are "Drīzumā"', async () => {
    demo()
    renderAt('/pakalpojumi')
    expect(await screen.findByText('Demonstrācija: šie dati nav publicēti pakalpojumi; pieteikumus nosūtīt nevar.')).toBeTruthy()
    const grid = await screen.findByRole('list', { name: 'Pakalpojumi' })
    const names = within(grid).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(names).toContain('Gaismekļu meistars')
    // Every service of this specialisation needs a qualification (none configured): not offered as orderable.
    expect(names).not.toContain('Santehnikas meistars')
    expect(names).not.toContain('Logu meistars')
    const soon = screen.getByRole('list', { name: 'Drīzumā' })
    expect(within(soon).getByText('Logu meistars')).toBeTruthy()
    expect(within(soon).queryByRole('link')).toBeNull() // planned: nothing to open or order
  })

  it('search narrows the cards', async () => {
    demo()
    renderAt('/pakalpojumi')
    await userEvent.type(await screen.findByLabelText('Meklēt pakalpojumu'), 'sifon')
    const grid = screen.getByRole('list', { name: 'Pakalpojumi' })
    expect(within(grid).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Izlietņu meistars'])
  })

  it('a specialisation page shows its real sections only, the confirmed prices and order links with the W-ID', async () => {
    demo()
    renderAt('/pakalpojumi/cm-s07')
    expect(await screen.findByRole('heading', { level: 1, name: 'Lampu un gaismekļu uzstādīšana Rīgā un Pierīgā' })).toBeTruthy()
    for (const heading of ['Izvēlies pakalpojumu', 'Ko varam izdarīt', 'Kas vajadzīgs pirms pieteikuma', 'Reāli paveiktie darbi', 'Kā notiek pasūtījums']) {
      expect(screen.getByRole('heading', { level: 2, name: heading })).toBeTruthy()
    }
    expect(screen.queryByRole('heading', { name: 'Biežāk uzdotie jautājumi' })).toBeNull() // no FAQ in this content
    expect(screen.getAllByText('Minimālā pasūtījuma summa — 40 €').length).toBeGreaterThan(0)
    // The approved materials line (owner decision 2026-11-04) is shown next to the minimum.
    expect(screen.getAllByText('Materiāli un palīgmateriāli tiek apmaksāti atsevišķi.').length).toBeGreaterThan(0)
    const order = screen.getByRole('link', { name: 'Pieteikt pakalpojumu: W092 Gaismekļa uzstādīšana pie esoša pieslēguma' })
    expect(order.getAttribute('href')).toBe('/pieteikums/jauns?w=W092')
    expect(document.title).toBe('Gaismekļu meistars · FIKSO')
  })

  it('a page with a FAQ but without photos shows the FAQ and no gallery', async () => {
    demo()
    renderAt('/pakalpojumi/cm-s03')
    expect(await screen.findByRole('heading', { level: 2, name: 'Biežāk uzdotie jautājumi' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Reāli paveiktie darbi' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Ko varam izdarīt' })).toBeNull()
  })

  it('a guest who orders goes straight to the form; signing in is optional and keeps the W-ID', async () => {
    demo()
    renderAt('/pakalpojumi/cm-s07')
    await userEvent.click(await screen.findByRole('link', { name: /Pieteikt pakalpojumu: W092/ }))
    expect(await screen.findByText('Tu piesaki: W092 — Gaismekļa uzstādīšana pie esoša pieslēguma')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Pieslēgties' })).toBeNull()
  })

  it('a client who chooses to sign in from the order form sees that the service is kept', async () => {
    renderAt('/login?returnTo=%2Fpieteikums%2Fjauns%3Fw%3DW092')
    expect(screen.getByText('Pieslēdzies, un izvēlētais pakalpojums saglabāsies. Pieteikt var arī bez reģistrācijas.')).toBeTruthy()
    const register = screen.getByRole('link', { name: 'Reģistrēties kā klients' })
    expect(decodeURIComponent(register.getAttribute('href') ?? '')).toContain('returnTo=/pieteikums/jauns?w=W092')
  })

  it('the order start shows the chosen service, checks the fields, and sends nothing', async () => {
    demo()
    const fetchMock = renderAt('/pieteikums/jauns?w=W092', client)
    expect(await screen.findByText('Tu piesaki: W092 — Gaismekļa uzstādīšana pie esoša pieslēguma')).toBeTruthy()
    expect(screen.getByText('Mazā santehnika un mājas meistaru darbi → Gaismekļu meistars')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByRole('alert').textContent).toBe('Apraksti, kas jāizdara.')
    await userEvent.type(screen.getByLabelText('Ko vajag izdarīt?'), 'Jāuzstāda griestu lustra.')
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    await userEvent.type(screen.getByLabelText('Adrese'), 'Brīvības iela 1, Rīga')
    await userEvent.click(await screen.findByRole('radio', { name: 'Rīga' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turpināt' }))
    expect(screen.getByRole('heading', { name: 'Pārbaudi pieteikumu' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nosūtīt pieteikumu' })).toHaveProperty('disabled', true)
    expect(screen.getByText(/Pieteikumu nosūtīšana vēl nav pieejama/)).toBeTruthy()
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0))
  })

  it('the confirmed prices in English', async () => {
    demo()
    applyLanguage('en')
    renderAt('/pakalpojumi/cm-s07')
    expect((await screen.findAllByText('€40/hour')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Minimum order value — €40').length).toBeGreaterThan(0)
    // No approved translation of the content yet: it stays Latvian (never auto-translated).
    expect(screen.getByRole('heading', { level: 1, name: 'Lampu un gaismekļu uzstādīšana Rīgā un Pierīgā' })).toBeTruthy()
  })

  it('the confirmed prices in Russian', async () => {
    demo()
    applyLanguage('ru')
    renderAt('/pakalpojumi/cm-s07')
    expect((await screen.findAllByText('40 €/час')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Минимальная стоимость заказа — 40 €').length).toBeGreaterThan(0)
  })
})
