import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../../App'
import { AuthContext, type AuthState } from '../../../auth/context'
import type { Page, User } from '../../../types/api'
import type { AdminMasterListItem, ReviewQueueItem } from '../../../types/masters'
import { MastersPage } from './MastersPage'
import { ReviewQueuePage } from './ReviewQueuePage'

const admin: User = {
  id: 'a1',
  role: 'admin',
  email: 'admin@example.lv',
  full_name: 'Admins',
  phone: null,
  status: 'active',
  master_approval_status: null,
  has_password: true,
  created_at: '2026-10-30T10:00:00Z',
}

function authState(user: User | null): AuthState {
  const noop = async () => {
    throw new Error('not used')
  }
  return { user, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

function master(over: Partial<AdminMasterListItem> = {}): AdminMasterListItem {
  return {
    id: 'm1',
    user_id: 'u1',
    full_name: 'Jānis Bērziņš',
    email: 'janis@example.lv',
    phone: '+37120000001',
    user_status: 'active',
    approval_status: 'pending_approval',
    decided_at: null,
    version: 1,
    registered_at: '2026-10-01T09:00:00Z',
    pending: { specialisations: 1, competencies: 2, qualifications: 1 },
    ...over,
  }
}

function queueItem(over: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    kind: 'specialisation',
    master_id: 'm1',
    master_name: 'Jānis Bērziņš',
    approval_status: 'pending_approval',
    user_status: 'active',
    item_id: 'sp1',
    name: 'Poda meistars',
    w_id: null,
    valid_until: null,
    since: '2026-11-01T08:30:00Z',
    version: 1,
    ...over,
  }
}

function page<T>(items: T[], next_cursor: string | null = null): Page<T> {
  return { items, next_cursor }
}

/** Answers GETs by path; records every requested URL. */
function mockApi(routes: Record<string, (url: URL) => Response>) {
  const urls: URL[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      const url = new URL(input, 'http://localhost')
      urls.push(url)
      const handler = routes[url.pathname]
      return handler ? handler(url) : new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'x' } }), { status: 404 })
    }),
  )
  return urls
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function renderPage(element: React.ReactNode, path: string) {
  return render(
    <AuthContext.Provider value={authState(admin)}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={path} element={element} />
          <Route path="/admin/masters/:id" element={<p>master card</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

// --- Meistari --------------------------------------------------------------------------------------------------

describe('MastersPage', () => {
  it('lists masters with their status, contacts and pending items', async () => {
    mockApi({
      '/api/v1/admin/masters': () =>
        json(
          page([
            master(),
            master({
              id: 'm2',
              full_name: 'Anna Kalniņa',
              phone: null,
              approval_status: 'approved',
              decided_at: '2026-10-20T10:00:00Z',
              user_status: 'blocked',
              pending: { specialisations: 0, competencies: 0, qualifications: 0 },
            }),
          ]),
        ),
    })
    renderPage(<MastersPage />, '/admin/masters')
    const list = await screen.findByRole('list', { name: 'Meistari' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(within(first).getByText('Jānis Bērziņš')).toBeTruthy()
    expect(within(first).getByText('Gaida apstiprinājumu')).toBeTruthy()
    expect(first.textContent).toContain('janis@example.lv · +37120000001')
    expect(first.textContent).toContain('Gaida lēmumu: specializācijas 1, kompetences 2, kvalifikācijas 1')
    expect(within(second).getByText('Apstiprināts')).toBeTruthy()
    expect(within(second).getByText('Bloķēts')).toBeTruthy()
    expect(second.textContent).toContain('Nav neizskatītu pieteikumu.')
    expect(second.textContent).toMatch(/Lēmums/)
  })

  it('sends the filters the API supports and replaces the list', async () => {
    const urls = mockApi({
      '/api/v1/admin/masters': (url) =>
        json(page(url.searchParams.get('approval_status') === 'approved' ? [master({ id: 'm9', full_name: 'Apstiprinātais' })] : [master()])),
    })
    const user = userEvent.setup()
    renderPage(<MastersPage />, '/admin/masters')
    await screen.findByText('Jānis Bērziņš')
    expect(urls[0].searchParams.get('approval_status')).toBeNull()
    expect(urls[0].searchParams.get('has_pending')).toBeNull()

    await user.selectOptions(screen.getByLabelText('Profila statuss'), 'approved')
    expect(await screen.findByText('Apstiprinātais')).toBeTruthy()
    expect(screen.queryByText('Jānis Bērziņš')).toBeNull()
    expect(urls.at(-1)?.searchParams.get('approval_status')).toBe('approved')

    await user.selectOptions(screen.getByLabelText('Neizskatīti pieteikumi'), 'yes')
    await waitFor(() => expect(urls.at(-1)?.searchParams.get('has_pending')).toBe('true'))
    await user.selectOptions(screen.getByLabelText('Neizskatīti pieteikumi'), 'no')
    await waitFor(() => expect(urls.at(-1)?.searchParams.get('has_pending')).toBe('false'))
    expect(urls.at(-1)?.searchParams.get('approval_status')).toBe('approved') // filters combine
  })

  it('loads more with the cursor and appends', async () => {
    const urls = mockApi({
      '/api/v1/admin/masters': (url) =>
        url.searchParams.get('cursor') === 'c2'
          ? json(page([master({ id: 'm2', full_name: 'Otrā lapa' })]))
          : json(page([master()], 'c2')),
    })
    const user = userEvent.setup()
    renderPage(<MastersPage />, '/admin/masters')
    await user.click(await screen.findByRole('button', { name: 'Ielādēt vairāk' }))
    expect(await screen.findByText('Otrā lapa')).toBeTruthy()
    expect(screen.getByText('Jānis Bērziņš')).toBeTruthy()
    expect(urls.at(-1)?.searchParams.get('cursor')).toBe('c2')
    expect(screen.queryByRole('button', { name: 'Ielādēt vairāk' })).toBeNull()
  })

  it('shows an empty state', async () => {
    mockApi({ '/api/v1/admin/masters': () => json(page([])) })
    renderPage(<MastersPage />, '/admin/masters')
    expect(await screen.findByText('Neviens meistars neatbilst filtram.')).toBeTruthy()
  })

  it('shows an API error in Latvian and retries', async () => {
    let fail = true
    mockApi({
      '/api/v1/admin/masters': () =>
        fail ? json({ error: { code: 'INVALID_CURSOR', message: 'x' } }, 400) : json(page([master()])),
    })
    const user = userEvent.setup()
    renderPage(<MastersPage />, '/admin/masters')
    expect((await screen.findByRole('alert')).textContent).toContain('Saraksta lappuse vairs nav derīga.')
    fail = false
    await user.click(screen.getByRole('button', { name: 'Mēģināt vēlreiz' }))
    expect(await screen.findByText('Jānis Bērziņš')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('opens the master card', async () => {
    mockApi({ '/api/v1/admin/masters': () => json(page([master()])) })
    const user = userEvent.setup()
    renderPage(<MastersPage />, '/admin/masters')
    const link = await screen.findByRole('link', { name: 'Jānis Bērziņš' })
    expect(link.getAttribute('href')).toBe('/admin/masters/m1')
    await user.click(link)
    expect(await screen.findByText('master card')).toBeTruthy()
  })
})

// --- Izskatīšanas rinda ----------------------------------------------------------------------------------------

describe('ReviewQueuePage', () => {
  it('lists every kind of pending item, oldest first as the API sends them', async () => {
    mockApi({
      '/api/v1/admin/review-queue': () =>
        json(
          page([
            queueItem(),
            queueItem({ kind: 'competency', item_id: 's1', name: 'Tualetes poda uzstādīšana', w_id: 'W071' }),
            queueItem({
              kind: 'qualification',
              item_id: 'q1',
              name: 'Elektrodrošība',
              valid_until: '2027-03-31',
              master_id: 'm2',
              master_name: 'Anna Kalniņa',
              user_status: 'blocked',
              approval_status: 'rejected',
            }),
          ]),
        ),
    })
    renderPage(<ReviewQueuePage />, '/admin/review-queue')
    const list = await screen.findByRole('list', { name: 'Izskatīšanas rinda' })
    const [spec, competency, qualification] = within(list).getAllByRole('listitem')
    expect(within(spec).getByText('Specializācija')).toBeTruthy()
    expect(spec.textContent).toContain('Poda meistars')
    expect(within(competency).getByText('Kompetence')).toBeTruthy()
    expect(within(competency).getByText('W071')).toBeTruthy()
    expect(within(qualification).getByText('Kvalifikācija')).toBeTruthy()
    expect(qualification.textContent).toContain('derīga līdz 31.03.2027')
    expect(qualification.textContent).toContain('Noraidīts · Bloķēts')
    expect(spec.textContent).toMatch(/Gaida kopš .*10:30/) // 08:30 UTC = 10:30 Riga
  })

  it('filters by kind', async () => {
    const urls = mockApi({
      '/api/v1/admin/review-queue': (url) =>
        json(page(url.searchParams.get('kind') === 'competency' ? [queueItem({ kind: 'competency', name: 'Tikai kompetence' })] : [queueItem()])),
    })
    const user = userEvent.setup()
    renderPage(<ReviewQueuePage />, '/admin/review-queue')
    await screen.findByText('Poda meistars')
    await user.selectOptions(screen.getByLabelText('Veids'), 'competency')
    expect(await screen.findByText('Tikai kompetence')).toBeTruthy()
    expect(screen.queryByText('Poda meistars')).toBeNull()
    expect(urls.at(-1)?.searchParams.get('kind')).toBe('competency')
  })

  it('shows an empty queue and errors', async () => {
    mockApi({ '/api/v1/admin/review-queue': () => json(page([])) })
    renderPage(<ReviewQueuePage />, '/admin/review-queue')
    expect(await screen.findByText('Nav neviena pieteikuma, kas gaida lēmumu.')).toBeTruthy()
  })

  it('shows a server error in Latvian', async () => {
    mockApi({ '/api/v1/admin/review-queue': () => json({ error: { code: 'SOMETHING', message: 'x' } }, 500) })
    renderPage(<ReviewQueuePage />, '/admin/review-queue')
    expect((await screen.findByRole('alert')).textContent).toContain('Radās kļūda. Mēģiniet vēlreiz.')
  })

  it('links each item to its master card', async () => {
    mockApi({ '/api/v1/admin/review-queue': () => json(page([queueItem()])) })
    const user = userEvent.setup()
    renderPage(<ReviewQueuePage />, '/admin/review-queue')
    const link = await screen.findByRole('link', { name: 'Atvērt meistara kartīti: Jānis Bērziņš' })
    expect(link.getAttribute('href')).toBe('/admin/masters/m1')
    await user.click(link)
    expect(await screen.findByText('master card')).toBeTruthy()
  })
})

// --- roles (UI convenience; the backend enforces them) --------------------------------------------------------

describe('admin master pages and roles', () => {
  function renderApp(path: string, user: User | null) {
    mockApi({
      '/api/v1/admin/masters': () => json(page([master()])),
      '/api/v1/admin/review-queue': () => json(page([queueItem()])),
    })
    render(
      <AuthContext.Provider value={authState(user)}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthContext.Provider>,
    )
  }

  it.each(['/admin/masters', '/admin/review-queue'])('%s is shown to an admin, with the navigation', async (path) => {
    renderApp(path, admin)
    expect(await screen.findByRole('heading', { level: 1 })).toBeTruthy()
    const nav = screen.getByRole('navigation', { name: 'Administrēšana' })
    expect(within(nav).getByRole('link', { name: 'Meistari' }).getAttribute('href')).toBe('/admin/masters')
    expect(within(nav).getByRole('link', { name: 'Izskatīšanas rinda' }).getAttribute('href')).toBe('/admin/review-queue')
  })

  it.each([
    ['master', 'Meistara panelis'],
    ['client', 'Mani pieteikumi'],
  ] as const)('a %s is sent to their own area', async (role, home) => {
    renderApp('/admin/masters', { ...admin, role })
    expect(await screen.findByRole('heading', { name: home })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Meistari' })).toBeNull()
  })

  it('an anonymous visitor is sent to login', async () => {
    renderApp('/admin/review-queue', null)
    expect(await screen.findByRole('button', { name: 'Pieslēgties' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Izskatīšanas rinda' })).toBeNull()
  })
})
