import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../../App'
import { AuthContext, type AuthState } from '../../../auth/context'
import type { User } from '../../../types/api'
import type { AdminMaster } from '../../../types/masters'

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

function card(over: Partial<AdminMaster> = {}): AdminMaster {
  return {
    id: 'm1',
    user_id: 'u1',
    full_name: 'Jānis Bērziņš',
    email: 'janis@example.lv',
    phone: '+37120000001',
    user_status: 'active',
    blocked_reason: null,
    approval_status: 'pending_approval',
    decided_by: null,
    decided_at: null,
    decision_reason: null,
    version: 3,
    registered_at: '2026-10-01T09:00:00Z',
    today: '2026-11-02',
    specialisations: [
      {
        specialisation_id: 'sp1',
        name: 'Santehniķis',
        status: 'requested',
        requested_at: '2026-10-02T08:00:00Z',
        decided_at: null,
        decided_by: null,
        decision_reason: null,
        version: 1,
      },
      {
        specialisation_id: 'sp2',
        name: 'Elektriķis',
        status: 'approved',
        requested_at: '2026-10-02T08:00:00Z',
        decided_at: '2026-10-03T08:00:00Z',
        decided_by: 'a1',
        decision_reason: null,
        version: 2,
      },
    ],
    competencies: [
      {
        service_id: 's1',
        w_id: 'W071',
        name: 'Tualetes poda uzstādīšana',
        specialisation_id: 'sp1',
        status: 'declared',
        declared_at: '2026-10-02T08:05:00Z',
        decided_at: null,
        decided_by: null,
        decision_reason: null,
        version: 1,
        eligible: false,
        reasons: [
          { code: 'SPECIALISATION_NOT_APPROVED', details: { specialisation_id: 'sp1', status: 'requested' } },
          { code: 'COMPETENCY_NOT_VERIFIED', details: { service_id: 's1', status: 'declared' } },
        ],
      },
      {
        service_id: 's2',
        w_id: 'W090',
        name: 'Rozetes nomaiņa',
        specialisation_id: 'sp2',
        status: 'verified',
        declared_at: '2026-10-02T08:05:00Z',
        decided_at: '2026-10-03T09:00:00Z',
        decided_by: 'a1',
        decision_reason: null,
        version: 4,
        eligible: true,
        reasons: [],
      },
    ],
    qualifications: [
      {
        id: 'mq1',
        qualification_id: 'q1',
        qualification_name: 'Elektrodrošības sertifikāts',
        status: 'submitted',
        document_number: 'EL-12345',
        valid_until: '2027-05-31',
        submitted_at: '2026-10-04T10:00:00Z',
        decided_at: null,
        decided_by: null,
        decision_reason: null,
        version: 1,
        expired: false,
        expires_soon: false,
        files: [
          { id: 'f1', mime_type: 'application/pdf', size_bytes: 20480, uploaded_at: '2026-10-04T10:00:00Z' },
          { id: 'f2', mime_type: 'image/png', size_bytes: 4096, uploaded_at: '2026-10-04T10:01:00Z' },
          { id: 'f3', mime_type: 'image/heic', size_bytes: 4096, uploaded_at: '2026-10-04T10:02:00Z' },
          { id: 'f4', mime_type: 'image/jpeg', size_bytes: 8192, uploaded_at: '2026-10-04T10:03:00Z' },
        ],
      },
      {
        id: 'mq2',
        qualification_id: 'q2',
        qualification_name: 'Gāzes iekārtu atļauja',
        status: 'verified',
        document_number: null,
        valid_until: '2026-10-31',
        submitted_at: '2026-09-04T10:00:00Z',
        decided_at: '2026-09-05T10:00:00Z',
        decided_by: 'a1',
        decision_reason: null,
        version: 2,
        expired: true,
        expires_soon: false,
        files: [],
      },
    ],
    qualification_types: [
      {
        id: 'q1',
        name: 'Elektrodrošības sertifikāts',
        description: null,
        status: 'active',
        requires_document: true,
        requires_document_number: true,
        requires_expiry_date: true,
        max_validity_months: 60,
        verifier_instructions: 'Pārbaudiet sertifikātu LEEA reģistrā.',
      },
    ],
    ...over,
  }
}

interface Call {
  method: string
  path: string
  search: string
  body: unknown
}

type Handler = (call: Call) => Response | Promise<Response>

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function apiError(status: number, code: string, details: Record<string, unknown> = {}): Response {
  return json({ error: { code, message: 'x', details } }, status)
}

/** Routes by "METHOD path"; records every call. Unknown routes answer 404. */
function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      const call: Call = {
        method: init?.method ?? 'GET',
        path: url.pathname,
        search: url.search,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const handler = routes[`${call.method} ${call.path}`]
      return handler ? handler(call) : apiError(404, 'NOT_FOUND')
    }),
  )
  return calls
}

const BASE = '/api/v1/admin/masters/m1'
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')
const gets = (calls: Call[]) => calls.filter((c) => c.method === 'GET' && c.path === BASE)

function renderCard(path = '/admin/masters/m1', user: User | null = admin) {
  return render(
    <AuthContext.Provider value={authState(user)}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

async function loaded() {
  return screen.findByRole('heading', { level: 1, name: 'Jānis Bērziņš' })
}

function section(name: string) {
  return screen.getByRole('list', { name })
}

function item(group: string, text: string) {
  const li = within(section(group))
    .getAllByRole('listitem')
    .find((el) => el.querySelector('.user-head')?.textContent?.includes(text))
  if (!li) throw new Error(`no ${text} in ${group}`)
  return li as HTMLElement
}

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>
let blobCount = 0

beforeEach(() => {
  blobCount = 0
  createObjectURL = vi.fn(() => `blob:fikso/${++blobCount}`)
  revokeObjectURL = vi.fn()
  URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL
  URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// --- loading ----------------------------------------------------------------------------------------------------

describe('master card: loading', () => {
  it('shows general information, the three groups and the qualification details', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card({ user_status: 'blocked', blocked_reason: 'Krāpšana' })) })
    renderCard()
    await loaded()
    expect(gets(calls)).toHaveLength(1)
    expect(screen.getByText('janis@example.lv')).toBeTruthy()
    expect(screen.getByText('+37120000001')).toBeTruthy()
    expect(screen.getByText('Bloķēts')).toBeTruthy()
    expect(screen.getByText(/Bloķēšanas iemesls: Krāpšana/)).toBeTruthy()
    expect(screen.getByText('Gaida apstiprinājumu')).toBeTruthy()
    expect(screen.getByText('Lēmums vēl nav pieņemts')).toBeTruthy()

    expect(within(item('Specializācijas', 'Santehniķis')).getByText('pieteikta')).toBeTruthy()
    expect(within(item('Specializācijas', 'Elektriķis')).getByText('apstiprināta')).toBeTruthy()

    expect(within(item('Kompetences', 'W071')).getByText('pieteikta')).toBeTruthy()
    expect(within(item('Kompetences', 'W090')).getByText('apstiprināta')).toBeTruthy()

    const submitted = item('Kvalifikācijas', 'Elektrodrošības sertifikāts')
    expect(within(submitted).getByText('EL-12345')).toBeTruthy()
    expect(within(submitted).getByText('31.05.2027')).toBeTruthy()
    expect(within(submitted).getByText(/LEEA reģistrā/)).toBeTruthy()
    expect(within(item('Kvalifikācijas', 'Gāzes')).getByText('Derīguma termiņš ir beidzies')).toBeTruthy()
  })

  it('shows the last profile decision with its reason', async () => {
    mockApi({
      [`GET ${BASE}`]: () =>
        json(card({ approval_status: 'rejected', decided_at: '2026-10-05T10:00:00Z', decision_reason: 'Nepilni dati' })),
    })
    renderCard()
    await loaded()
    expect(screen.getByText(/Iemesls: Nepilni dati/)).toBeTruthy()
    expect(screen.getByText('Noraidīts')).toBeTruthy()
  })

  it('labels the kept decision of a re-application as the previous one', async () => {
    const again = card()
    again.specialisations[0] = { ...again.specialisations[0], decided_at: '2026-10-03T08:00:00Z', decision_reason: 'Nav pieredzes' }
    mockApi({ [`GET ${BASE}`]: () => json(again) })
    renderCard()
    await loaded()
    // sp1 is "requested" again: the decision on the row is the earlier one, not a decision on this application.
    expect(within(item('Specializācijas', 'Santehniķis')).getByText(/^Iepriekšējais lēmums: .* · Iemesls: Nav pieredzes$/)).toBeTruthy()
    expect(within(item('Specializācijas', 'Elektriķis')).getByText(/^Lēmums: /)).toBeTruthy()
  })

  it('shows empty groups', async () => {
    mockApi({ [`GET ${BASE}`]: () => json(card({ specialisations: [], competencies: [], qualifications: [] })) })
    renderCard()
    await loaded()
    expect(screen.getByText('Meistars nav pieteicis nevienu specializāciju.')).toBeTruthy()
    expect(screen.getByText('Meistars nav pieteicis nevienu pakalpojumu.')).toBeTruthy()
    expect(screen.getByText('Meistars nav iesniedzis nevienu kvalifikāciju.')).toBeTruthy()
  })

  it('reports an unknown master in Latvian without a retry', async () => {
    mockApi({ [`GET /api/v1/admin/masters/nope`]: () => apiError(404, 'MASTER_NOT_FOUND') })
    renderCard('/admin/masters/nope')
    expect((await screen.findByRole('alert')).textContent).toContain('Meistars nav atrasts.')
    expect(screen.queryByRole('button', { name: 'Mēģināt vēlreiz' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Atpakaļ uz meistaru sarakstu' }).getAttribute('href')).toBe('/admin/masters')
  })

  it('shows a server error and retries', async () => {
    let fail = true
    const calls = mockApi({
      [`GET ${BASE}`]: () => (fail ? new Response('down', { status: 502 }) : json(card())),
    })
    renderCard()
    expect((await screen.findByRole('alert')).textContent).toContain('Radās kļūda. Mēģiniet vēlreiz.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Mēģināt vēlreiz' }))
    await loaded()
    expect(gets(calls)).toHaveLength(2)
  })
})

// --- decisions --------------------------------------------------------------------------------------------------

describe('master card: decisions', () => {
  function buttons(el: HTMLElement) {
    return within(el)
      .queryAllByRole('button')
      .map((b) => b.textContent)
      .filter((text) => ['Apstiprināt', 'Noraidīt', 'Atsaukt'].includes(text ?? ''))
  }

  it('offers only the decisions the status allows', async () => {
    mockApi({
      [`GET ${BASE}`]: () =>
        json(
          card({
            specialisations: [
              ...card().specialisations,
              { ...card().specialisations[0], specialisation_id: 'sp3', name: 'Flīzētājs', status: 'withdrawn' },
            ],
          }),
        ),
    })
    renderCard()
    await loaded()
    const general = screen.getByRole('heading', { name: 'Pamatinformācija' }).closest('section') as HTMLElement
    expect(buttons(general)).toEqual(['Apstiprināt', 'Noraidīt'])
    expect(buttons(item('Specializācijas', 'Santehniķis'))).toEqual(['Apstiprināt', 'Noraidīt'])
    expect(buttons(item('Specializācijas', 'Elektriķis'))).toEqual(['Atsaukt'])
    expect(buttons(item('Specializācijas', 'Flīzētājs'))).toEqual([])
    expect(buttons(item('Kompetences', 'W071'))).toEqual(['Apstiprināt', 'Noraidīt'])
    expect(buttons(item('Kompetences', 'W090'))).toEqual(['Atsaukt'])
    expect(buttons(item('Kvalifikācijas', 'Elektrodrošības'))).toEqual(['Apstiprināt', 'Noraidīt'])
    expect(buttons(item('Kvalifikācijas', 'Gāzes'))).toEqual(['Atsaukt'])
  })

  it.each([
    ['rejected', ['Apstiprināt']],
    ['approved', []],
  ] as const)('a %s profile offers %j', async (status, expected) => {
    mockApi({ [`GET ${BASE}`]: () => json(card({ approval_status: status })) })
    renderCard()
    await loaded()
    const general = screen.getByRole('heading', { name: 'Pamatinformācija' }).closest('section') as HTMLElement
    expect(buttons(general)).toEqual(expected)
  })

  const ONE_CLICK = [
    ['specialisation approve', 'Apstiprināt: Santehniķis', `${BASE}/specialisations/sp1/approve`, 1],
    ['competency verify', 'Apstiprināt: W071 Tualetes poda uzstādīšana', `${BASE}/competencies/s1/verify`, 1],
    ['qualification verify', 'Apstiprināt: Elektrodrošības sertifikāts', `${BASE}/qualifications/mq1/verify`, 1],
  ] as const

  it.each(ONE_CLICK)('%s posts only expected_version', async (_name, button, path, version) => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()), [`POST ${path}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: button }))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toEqual([{ method: 'POST', path, search: '', body: { expected_version: version } }])
  })

  const REASONED = [
    ['profile reject', 'Noraidīt: Jānis Bērziņš', `${BASE}/reject`, 3, 'Apstiprināt noraidīšanu'],
    ['specialisation reject', 'Noraidīt: Santehniķis', `${BASE}/specialisations/sp1/reject`, 1, 'Apstiprināt noraidīšanu'],
    ['specialisation revoke', 'Atsaukt: Elektriķis', `${BASE}/specialisations/sp2/revoke`, 2, 'Apstiprināt atsaukšanu'],
    ['competency reject', 'Noraidīt: W071 Tualetes poda uzstādīšana', `${BASE}/competencies/s1/reject`, 1, 'Apstiprināt noraidīšanu'],
    ['competency revoke', 'Atsaukt: W090 Rozetes nomaiņa', `${BASE}/competencies/s2/revoke`, 4, 'Apstiprināt atsaukšanu'],
    ['qualification reject', 'Noraidīt: Elektrodrošības sertifikāts', `${BASE}/qualifications/mq1/reject`, 1, 'Apstiprināt noraidīšanu'],
    ['qualification revoke', 'Atsaukt: Gāzes iekārtu atļauja', `${BASE}/qualifications/mq2/revoke`, 2, 'Apstiprināt atsaukšanu'],
  ] as const

  it('shows no eligibility reasons as verification blockers before a verify attempt', async () => {
    mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    const declared = item('Kompetences', 'W071')
    // The card data says why the master does not qualify yet; that is not what blocks a verification.
    expect(within(declared).queryByText('Pakalpojuma specializācija meistaram nav apstiprināta')).toBeNull()
    expect(within(declared).queryByText('Kompetence nav apstiprināta')).toBeNull()
    expect(within(declared).queryByRole('list')).toBeNull()
    expect(within(declared).queryByRole('alert')).toBeNull()
    expect(screen.queryByText('Apstiprināt nevar:')).toBeNull()
  })

  it.each(REASONED)('%s asks for a reason and a confirmation', async (_name, button, path, version, confirm) => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()), [`POST ${path}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: button }))
    expect(posts(calls)).toHaveLength(0) // opening the form sends nothing
    const field = screen.getByLabelText('Iemesls (obligāts)')
    expect(document.activeElement).toBe(field)
    await userEvent.type(field, '  Dokuments neatbilst  ')
    await userEvent.click(screen.getByRole('button', { name: confirm }))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toEqual([
      { method: 'POST', path, search: '', body: { expected_version: version, reason: 'Dokuments neatbilst' } },
    ])
    expect(screen.queryByLabelText('Iemesls (obligāts)')).toBeNull()
  })

  it('warns that a group rejection is final, not a profile rejection', async () => {
    mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Noraidīt: Santehniķis' }))
    expect(screen.getByText(/Šis lēmums ir galīgs/)).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Atcelt' }))
    await userEvent.click(screen.getByRole('button', { name: 'Noraidīt: Jānis Bērziņš' }))
    expect(screen.queryByText(/Šis lēmums ir galīgs/)).toBeNull()
  })

  it.each(['', '   '])('refuses an empty reason (%j) without a request', async (text) => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    if (text) await userEvent.type(screen.getByLabelText('Iemesls (obligāts)'), text)
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt atsaukšanu' }))
    expect(screen.getByRole('alert').textContent).toBe('Norādiet iemeslu.')
    expect(screen.getByLabelText('Iemesls (obligāts)').getAttribute('aria-invalid')).toBe('true')
    expect(posts(calls)).toHaveLength(0)
  })

  it('limits the reason to 1000 characters', async () => {
    mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    expect(screen.getByLabelText('Iemesls (obligāts)').getAttribute('maxlength')).toBe('1000')
  })

  it('cancelling the reason form sends nothing', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    await userEvent.click(screen.getByRole('button', { name: 'Atcelt' }))
    expect(screen.queryByLabelText('Iemesls (obligāts)')).toBeNull()
    expect(posts(calls)).toHaveLength(0)
  })

  it('shows the card the decision returns (no stale state)', async () => {
    const after = card()
    after.specialisations[0] = { ...after.specialisations[0], status: 'approved', version: 2, decided_at: '2026-11-02T10:00:00Z' }
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp1/approve`]: () => json(after),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' }))
    const row = item('Specializācijas', 'Santehniķis')
    await waitFor(() => expect(within(row).getByText('apstiprināta')).toBeTruthy())
    expect(within(row).getByRole('button', { name: 'Atsaukt: Santehniķis' })).toBeTruthy()
    expect(within(row).queryByRole('button', { name: 'Apstiprināt: Santehniķis' })).toBeNull()
  })

  it('the next decision uses the version from the returned card', async () => {
    const after = card()
    after.specialisations[0] = { ...after.specialisations[0], status: 'approved', version: 2 }
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp1/approve`]: () => json(after),
      [`POST ${BASE}/specialisations/sp1/revoke`]: () => json(after),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Atsaukt: Santehniķis' }))
    await userEvent.type(screen.getByLabelText('Iemesls (obligāts)'), 'Kļūda')
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt atsaukšanu' }))
    await waitFor(() => expect(posts(calls)).toHaveLength(2))
    expect(posts(calls)[1].body).toEqual({ expected_version: 2, reason: 'Kļūda' })
  })

  it('on VERSION_CONFLICT reloads the card, keeps the reason and retries with the new version', async () => {
    let conflict = true
    const fresh = card()
    fresh.specialisations[1] = { ...fresh.specialisations[1], version: 5, decision_reason: null }
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(conflict ? card() : fresh),
      [`POST ${BASE}/specialisations/sp2/revoke`]: () => {
        if (conflict) {
          conflict = false
          return apiError(409, 'VERSION_CONFLICT', { status: 'approved', version: 5 })
        }
        return json(fresh)
      },
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    await userEvent.type(screen.getByLabelText('Iemesls (obligāts)'), 'Licence anulēta')
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt atsaukšanu' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Kāds šo ierakstu jau ir mainījis')
    await waitFor(() => expect(gets(calls)).toHaveLength(2))
    expect((screen.getByLabelText('Iemesls (obligāts)') as HTMLTextAreaElement).value).toBe('Licence anulēta')
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt atsaukšanu' }))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls).map((c) => c.body)).toEqual([
      { expected_version: 2, reason: 'Licence anulēta' },
      { expected_version: 5, reason: 'Licence anulēta' },
    ])
  })

  it('after VERSION_CONFLICT shows a decision someone else made and offers no stale action', async () => {
    const decided = card()
    decided.competencies[0] = { ...decided.competencies[0], status: 'rejected', version: 2, decided_at: '2026-11-02T09:00:00Z', decision_reason: 'Cits admins' }
    let reloaded = false
    mockApi({
      [`GET ${BASE}`]: () => json(reloaded ? decided : card()),
      [`POST ${BASE}/competencies/s1/verify`]: () => {
        reloaded = true
        return apiError(409, 'VERSION_CONFLICT', { status: 'rejected', version: 2 })
      },
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: W071 Tualetes poda uzstādīšana' }))
    const row = item('Kompetences', 'W071')
    await waitFor(() => expect(within(row).getByText('noraidīta')).toBeTruthy())
    expect(within(row).getByText(/Iemesls: Cits admins/)).toBeTruthy()
    expect(within(row).queryByRole('button', { name: /Apstiprināt:/ })).toBeNull()
    expect(within(row).getByRole('alert').textContent).toContain('Kāds šo ierakstu jau ir mainījis')
  })

  it('shows why a competency cannot be verified (409 details.reasons)', async () => {
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/competencies/s1/verify`]: () =>
        apiError(409, 'SPECIALISATION_NOT_APPROVED', {
          reasons: [
            { code: 'SPECIALISATION_NOT_APPROVED', details: { specialisation_id: 'sp1', status: 'requested' } },
            { code: 'QUALIFICATION_MISSING', details: { qualification_id: 'q1', name: 'Elektrodrošības sertifikāts', latest_status: null } },
            { code: 'QUALIFICATION_EXPIRED', details: { qualification_id: 'q2', name: 'Gāzes iekārtu atļauja', valid_until: '2026-10-31' } },
          ],
        }),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: W071 Tualetes poda uzstādīšana' }))
    const alert = await within(item('Kompetences', 'W071')).findByRole('alert')
    expect(alert.textContent).toContain('Apstiprināt nevar:')
    expect(within(alert).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Pakalpojuma specializācija meistaram nav apstiprināta',
      'Nav apstiprinātas nepieciešamās kvalifikācijas: Elektrodrošības sertifikāts',
      'Kvalifikācijas derīguma termiņš ir beidzies: Gāzes iekārtu atļauja (derīga līdz 31.10.2026)',
    ])
  })

  it('shows why a qualification cannot be verified', async () => {
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/qualifications/mq1/verify`]: () =>
        apiError(409, 'QUALIFICATION_TYPE_NOT_ACTIVE', {
          reasons: [{ code: 'QUALIFICATION_TYPE_NOT_ACTIVE', details: { qualification_id: 'q1', status: 'archived' } }],
        }),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Elektrodrošības sertifikāts' }))
    const alert = await within(item('Kvalifikācijas', 'Elektrodrošības')).findByRole('alert')
    expect(within(alert).getByRole('listitem').textContent).toBe('Kvalifikācijas veids katalogā nav aktīvs')
  })

  it.each([
    ['INVALID_TRANSITION', 409, 'Šis lēmums ieraksta pašreizējā statusā nav iespējams.'],
    ['SPECIALISATION_NOT_AVAILABLE', 409, 'Šī specializācija katalogā vairs netiek piedāvāta.'],
    ['DECISION_FORBIDDEN', 403, 'Jūs nevarat pieņemt lēmumus par šo meistaru.'],
    ['SPECIALISATION_NOT_FOUND', 404, 'Specializācija nav atrasta.'],
    ['REASON_REQUIRED', 422, 'Norādiet iemeslu.'],
    ['SOMETHING_NEW', 500, 'Radās kļūda. Mēģiniet vēlreiz.'],
  ])('reports %s in Latvian at the item and keeps the card', async (code, status, text) => {
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp1/approve`]: () => apiError(status, code),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' }))
    const alert = await within(item('Specializācijas', 'Santehniķis')).findByRole('alert')
    expect(alert.textContent).toBe(text)
    expect(gets(calls)).toHaveLength(1) // only a version conflict reloads
    expect(screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' })).toHaveProperty('disabled', false)
  })

  it('keeps the reason form open with its text after an error', async () => {
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/qualifications/mq1/reject`]: () => new Response('gateway', { status: 502 }),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Noraidīt: Elektrodrošības sertifikāts' }))
    await userEvent.type(screen.getByLabelText('Iemesls (obligāts)'), 'Nesalasāms')
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt noraidīšanu' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Radās kļūda. Mēģiniet vēlreiz.')
    expect((screen.getByLabelText('Iemesls (obligāts)') as HTMLTextAreaElement).value).toBe('Nesalasāms')
  })

  it('a double click sends one decision and disables every decision button meanwhile', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp1/approve`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    await loaded()
    const approve = screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' })
    await userEvent.dblClick(approve)
    await userEvent.click(approve)
    expect(posts(calls)).toHaveLength(1)
    expect(approve.textContent).toBe('Saglabā…')
    expect(approve).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' })).toHaveProperty('disabled', true)
    await act(async () => release(json(card())))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toHaveLength(1)
  })

  it('a double submit of a reason sends one decision', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp2/revoke`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    const field = screen.getByLabelText('Iemesls (obligāts)')
    await userEvent.type(field, 'Iemesls')
    await userEvent.dblClick(screen.getByRole('button', { name: 'Apstiprināt atsaukšanu' }))
    await userEvent.type(field, '{Enter}')
    expect(posts(calls)).toHaveLength(1)
    await act(async () => release(json(card())))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toHaveLength(1)
  })
  it('two submits in the same tick still send one decision (the in-flight guard, not only the disabled button)', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp2/revoke`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt: Elektriķis' }))
    const field = screen.getByLabelText('Iemesls (obligāts)')
    await userEvent.type(field, 'Iemesls')
    const form = field.closest('form') as HTMLFormElement
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })
    await waitFor(() => expect(posts(calls)).toHaveLength(1))
    await act(async () => release(json(card())))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toHaveLength(1)
  })
})

describe('master card: profile approval confirmation', () => {
  async function openDialog() {
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Jānis Bērziņš' }))
    return screen.getByRole('alertdialog', { name: 'Apstiprināt meistara profilu?' })
  }

  it('asks first, says the decision is final and sends nothing yet', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    const dialog = await openDialog()
    expect(dialog.textContent).toContain('Šis lēmums ir galīgs')
    expect(dialog.textContent).toContain('vairs nevar atgriezt iepriekšējā statusā')
    expect(dialog.textContent).toContain('Jānis Bērziņš')
    expect(document.activeElement).toBe(dialog)
    expect(posts(calls)).toHaveLength(0)
  })

  it('cancel closes the dialog without a request and returns focus', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    const dialog = await openDialog()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Atcelt' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Apstiprināt: Jānis Bērziņš' }))
    expect(posts(calls)).toHaveLength(0)
  })

  it('Escape closes the dialog without a request', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await openDialog()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(posts(calls)).toHaveLength(0)
  })

  it('confirming sends expected_version once and shows the approved profile', async () => {
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/approve`]: () =>
        json(card({ approval_status: 'approved', version: 4, decided_at: '2026-11-02T10:00:00Z' })),
    })
    renderCard()
    const dialog = await openDialog()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt' }))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(posts(calls)).toEqual([{ method: 'POST', path: `${BASE}/approve`, search: '', body: { expected_version: 3 } }])
    expect(screen.getByText('Apstiprināts')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Apstiprināt: Jānis Bērziņš' })).toBeNull()
    // The opener is gone with the decision: focus goes to the main content, not to the top of the document.
    expect(document.activeElement).toBe(document.getElementById('main'))
  })

  it('a double click on the confirmation sends one request and locks the dialog meanwhile', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/approve`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    const dialog = await openDialog()
    const confirm = within(dialog).getByRole('button', { name: 'Apstiprināt' })
    await userEvent.dblClick(confirm)
    expect(posts(calls)).toHaveLength(1)
    expect(confirm.textContent).toBe('Saglabā…')
    expect(confirm).toHaveProperty('disabled', true)
    expect(within(dialog).getByRole('button', { name: 'Atcelt' })).toHaveProperty('disabled', true)
    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('alertdialog')).toBeTruthy() // no escape while the request runs
    await act(async () => release(json(card({ approval_status: 'approved', version: 4 }))))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toHaveLength(1)
  })

  it('two confirmations in the same tick still send one request', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/approve`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    const dialog = await openDialog()
    const confirm = within(dialog).getByRole('button', { name: 'Apstiprināt' })
    act(() => {
      confirm.click()
      confirm.click()
    })
    await waitFor(() => expect(posts(calls)).toHaveLength(1))
    await act(async () => release(json(card({ approval_status: 'approved', version: 4 }))))
    expect(await screen.findByText('Lēmums saglabāts.')).toBeTruthy()
    expect(posts(calls)).toHaveLength(1)
  })

  it('on VERSION_CONFLICT closes the dialog, reloads the card and shows the message', async () => {
    let reloaded = false
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(reloaded ? card({ approval_status: 'approved', version: 4 }) : card()),
      [`POST ${BASE}/approve`]: () => {
        reloaded = true
        return apiError(409, 'VERSION_CONFLICT', { status: 'approved', version: 4 })
      },
    })
    renderCard()
    const dialog = await openDialog()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Kāds šo ierakstu jau ir mainījis')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await waitFor(() => expect(gets(calls)).toHaveLength(2))
    expect(screen.getByText('Apstiprināts')).toBeTruthy()
  })

  it('profile rejection still asks for a reason, without the approval dialog', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()), [`POST ${BASE}/reject`]: () => json(card()) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Noraidīt: Jānis Bērziņš' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt noraidīšanu' }))
    expect(screen.getByRole('alert').textContent).toBe('Norādiet iemeslu.')
    expect(posts(calls)).toHaveLength(0)
  })

  it('a specialisation approval stays one click (no dialog)', async () => {
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`POST ${BASE}/specialisations/sp1/approve`]: () => json(card()),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: Santehniķis' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await waitFor(() => expect(posts(calls)).toHaveLength(1))
  })
})

// --- documents --------------------------------------------------------------------------------------------------

describe('master card: documents', () => {
  const FILES = `${BASE}/qualifications/mq1/files`

  function fileResponse(type: string, disposition: string) {
    return () =>
      // A string body: jsdom's Blob has no stream(), which Node 22's Response needs.
      new Response('data', {
        status: 200,
        headers: { 'Content-Type': type, 'Content-Disposition': disposition },
      })
  }

  const viewer = () => screen.queryByRole('img', { name: 'Dokumenta skats' })

  it('views an image through the admin route in a Blob URL and revokes it on close', async () => {
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f2`]: fileResponse('image/png', 'inline; filename="f2.png"'),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Skatīt: Dokuments 2 (Elektrodrošības sertifikāts)' }))
    const image = await screen.findByRole('img', { name: 'Dokumenta skats' })
    expect(image.getAttribute('src')).toBe('blob:fikso/1')
    expect(calls.find((c) => c.path === `${FILES}/f2`)?.search).toBe('?mode=view')
    expect(revokeObjectURL).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Aizvērt skatu' }))
    expect(viewer()).toBeNull()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fikso/1')
  })

  it('revokes the previous image when another one opens', async () => {
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f2`]: fileResponse('image/png', 'inline; filename="f2.png"'),
      [`GET ${FILES}/f4`]: fileResponse('image/jpeg', 'inline; filename="f4.jpg"'),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: /Skatīt: Dokuments 2/ }))
    await screen.findByRole('img', { name: 'Dokumenta skats' })
    await userEvent.click(screen.getByRole('button', { name: /Skatīt: Dokuments 4/ }))
    await waitFor(() => expect(viewer()?.getAttribute('src')).toBe('blob:fikso/2'))
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fikso/1')
    expect(revokeObjectURL).not.toHaveBeenCalledWith('blob:fikso/2')
    expect(screen.getAllByRole('img', { name: 'Dokumenta skats' })).toHaveLength(1)
  })

  it('revokes an open image when the card unmounts', async () => {
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f2`]: fileResponse('image/png', 'inline; filename="f2.png"'),
    })
    const { unmount } = renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: /Skatīt: Dokuments 2/ }))
    await screen.findByRole('img', { name: 'Dokumenta skats' })
    unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fikso/1')
  })

  it('creates no Blob URL when the card is gone before the image arrives', async () => {
    let release: (r: Response) => void = () => {}
    mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f2`]: () => new Promise<Response>((r) => (release = r)),
    })
    const { unmount } = renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: /Skatīt: Dokuments 2/ }))
    unmount()
    await act(async () => release(fileResponse('image/png', 'inline')()))
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it.each([
    ['PDF', 1],
    ['HEIC', 3],
  ])('a %s is never viewed: no view button, no inline Blob URL', async (_kind, index) => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    expect(screen.queryByRole('button', { name: new RegExp(`Skatīt: Dokuments ${index}`) })).toBeNull()
    expect(screen.getByRole('button', { name: new RegExp(`Lejupielādēt: Dokuments ${index}`) })).toBeTruthy()
    expect(calls.filter((c) => c.path.includes('/files/'))).toHaveLength(0)
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(document.querySelector('iframe, object, embed')).toBeNull()
  })

  it('downloads a PDF with the server file name and revokes the Blob URL at once, never showing it', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f1`]: fileResponse('application/pdf', 'attachment; filename="f1.pdf"'),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Lejupielādēt: Dokuments 1 (Elektrodrošības sertifikāts)' }))
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    const link = click.mock.contexts[0] as HTMLAnchorElement
    expect(link.download).toBe('f1.pdf')
    expect(link.href).toBe('blob:fikso/1')
    expect(link.isConnected).toBe(false) // a detached link: nothing in the page points at the file
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fikso/1')
    expect(calls.filter((c) => c.path === `${FILES}/f1`).map((c) => c.search)).toEqual(['?mode=download'])
    expect(viewer()).toBeNull()
    expect(document.querySelector('iframe, object, embed')).toBeNull()
  })

  it('downloads a HEIC image the same way', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f3`]: fileResponse('image/heic', 'attachment; filename="f3.heic"'),
    })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: /Lejupielādēt: Dokuments 3/ }))
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('f3.heic')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fikso/1')
    expect(calls.find((c) => c.path === `${FILES}/f3`)?.search).toBe('?mode=download')
    expect(viewer()).toBeNull()
  })

  it('a double click fetches the image once', async () => {
    let release: (r: Response) => void = () => {}
    const calls = mockApi({
      [`GET ${BASE}`]: () => json(card()),
      [`GET ${FILES}/f2`]: () => new Promise<Response>((r) => (release = r)),
    })
    renderCard()
    await loaded()
    await userEvent.dblClick(screen.getByRole('button', { name: /Skatīt: Dokuments 2/ }))
    expect(calls.filter((c) => c.path === `${FILES}/f2`)).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Lejupielādēt: Dokuments 1/ })).toHaveProperty('disabled', true)
    await act(async () => release(fileResponse('image/png', 'inline')()))
    await screen.findByRole('img', { name: 'Dokumenta skats' })
    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['FILE_NOT_FOUND', 404, 'Dokuments nav atrasts.'],
    ['FILE_UNAVAILABLE', 404, 'Dokuments šobrīd nav pieejams.'],
    ['FORBIDDEN', 403, 'Jums nav piekļuves šai darbībai.'],
  ])('reports %s in Latvian and creates no Blob URL', async (code, status, text) => {
    mockApi({ [`GET ${BASE}`]: () => json(card()), [`GET ${FILES}/f2`]: () => apiError(status, code) })
    renderCard()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: /Skatīt: Dokuments 2/ }))
    expect((await screen.findByRole('alert')).textContent).toBe(text)
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it('shows a qualification without files', async () => {
    mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard()
    await loaded()
    expect(within(item('Kvalifikācijas', 'Gāzes')).getByText('Dokumenti nav pievienoti.')).toBeTruthy()
  })
})

// --- roles (UI convenience; the backend enforces them) ----------------------------------------------------------

describe('master card: roles', () => {
  it.each([
    ['master', 'Meistara panelis'],
    ['client', 'Mani pieteikumi'],
  ] as const)('a %s is sent to their own area and the card is never requested', async (role, home) => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard('/admin/masters/m1', { ...admin, role })
    expect(await screen.findByRole('heading', { name: home })).toBeTruthy()
    expect(gets(calls)).toHaveLength(0)
    expect(screen.queryByText('Jānis Bērziņš')).toBeNull()
  })

  it('an anonymous visitor is sent to login', async () => {
    const calls = mockApi({ [`GET ${BASE}`]: () => json(card()) })
    renderCard('/admin/masters/m1', null)
    expect(await screen.findByRole('button', { name: 'Pieslēgties' })).toBeTruthy()
    expect(gets(calls)).toHaveLength(0)
  })

  it('an admin reaches the card from the masters list', async () => {
    mockApi({
      [`GET /api/v1/admin/masters`]: () =>
        json({
          items: [
            {
              id: 'm1',
              user_id: 'u1',
              full_name: 'Jānis Bērziņš',
              email: 'janis@example.lv',
              phone: null,
              user_status: 'active',
              approval_status: 'pending_approval',
              decided_at: null,
              version: 3,
              registered_at: '2026-10-01T09:00:00Z',
              pending: { specialisations: 1, competencies: 1, qualifications: 1 },
            },
          ],
          next_cursor: null,
        }),
      [`GET ${BASE}`]: () => json(card()),
    })
    renderCard('/admin/masters')
    await userEvent.click(await screen.findByRole('link', { name: 'Jānis Bērziņš' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Specializācijas' })).toBeTruthy()
  })
})
