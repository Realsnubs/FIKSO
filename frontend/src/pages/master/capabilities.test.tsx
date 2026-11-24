import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../App'
import { AuthContext, type AuthState } from '../../auth/context'
import type { MasterApprovalStatus, User } from '../../types/api'
import type { Capabilities, MasterCatalogue, Submission } from '../../types/capabilities'

const masterUser: User = {
  id: 'u1',
  role: 'master',
  email: 'janis@example.lv',
  full_name: 'Jānis Bērziņš',
  phone: '+37120000001',
  status: 'active',
  master_approval_status: 'pending_approval',
  has_password: true,
  created_at: '2026-10-01T09:00:00Z',
}

function auth(user: User | null): AuthState {
  const noop = async () => {
    throw new Error('not used')
  }
  return { user, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

const CATALOGUE: MasterCatalogue = {
  specialisations: [
    {
      id: 'sp1',
      category_id: 'c1',
      name: 'Santehniķis',
      description: null,
      status: 'active',
      qualification_required: false,
      qualification_ids: [],
      services: [
        { id: 's1', w_id: 'W071', name: 'Tualetes poda uzstādīšana', status: 'active', qualification_required: false, qualification_ids: ['q2'] },
        { id: 's2', w_id: 'W072', name: 'Izlietnes uzstādīšana', status: 'active', qualification_required: false, qualification_ids: [] },
        { id: 's5', w_id: 'W075', name: 'Ūdens sildītāja pieslēgšana', status: 'planned', qualification_required: false, qualification_ids: [] },
      ],
    },
    {
      id: 'sp2',
      category_id: 'c1',
      name: 'Elektriķis',
      description: null,
      status: 'active',
      qualification_required: true,
      qualification_ids: ['q1'],
      services: [
        { id: 's3', w_id: 'W080', name: 'Rozetes nomaiņa', status: 'active', qualification_required: false, qualification_ids: [] },
      ],
    },
    { id: 'sp3', category_id: 'c1', name: 'Flīzētājs', description: null, status: 'planned', qualification_required: false, qualification_ids: [], services: [] },
  ],
  qualification_types: [
    {
      id: 'q1',
      name: 'Elektrodrošības sertifikāts',
      description: 'Sertifikāts darbam ar elektroiekārtām.',
      status: 'active',
      requires_document: true,
      requires_document_number: true,
      requires_expiry_date: true,
      max_validity_months: 60,
    },
    {
      id: 'q2',
      name: 'Darba drošības apmācība',
      description: null,
      status: 'active',
      requires_document: true,
      requires_document_number: false,
      requires_expiry_date: false,
      max_validity_months: null,
    },
    {
      id: 'q3',
      name: 'Augstuma darbu apliecība',
      description: null,
      status: 'active',
      requires_document: true,
      requires_document_number: false,
      requires_expiry_date: false,
      max_validity_months: null,
    },
  ],
}

function submission(over: Partial<Submission>): Submission {
  return {
    id: 'mq',
    qualification_id: 'q1',
    qualification_name: 'Elektrodrošības sertifikāts',
    status: 'submitted',
    document_number: null,
    valid_until: null,
    submitted_at: '2026-10-04T10:00:00Z',
    decided_at: null,
    decision_reason: null,
    expired: false,
    expires_soon: false,
    files: [],
    ...over,
  }
}

function initialCaps(approval: MasterApprovalStatus = 'pending_approval'): Capabilities {
  return {
    approval_status: approval,
    rejection_reason: approval === 'rejected' ? 'Nepilni dati' : null,
    today: '2026-11-02',
    specialisations: [
      { specialisation_id: 'sp2', name: 'Elektriķis', status: 'requested', requested_at: '2026-10-02T08:00:00Z', decided_at: null, decision_reason: null },
      { specialisation_id: 'sp1', name: 'Santehniķis', status: 'approved', requested_at: '2026-10-02T08:00:00Z', decided_at: '2026-10-03T08:00:00Z', decision_reason: null },
      { specialisation_id: 'sp9', name: 'Jumiķis', status: 'rejected', requested_at: '2026-10-02T08:00:00Z', decided_at: '2026-10-03T08:00:00Z', decision_reason: 'Nav pieredzes' },
    ],
    competencies: [
      {
        service_id: 's1', w_id: 'W071', name: 'Tualetes poda uzstādīšana', specialisation_id: 'sp1', status: 'verified',
        declared_at: '2026-10-02T08:05:00Z', decided_at: '2026-10-03T09:00:00Z', decision_reason: null, eligible: true, reasons: [],
      },
      {
        service_id: 's2', w_id: 'W072', name: 'Izlietnes uzstādīšana', specialisation_id: 'sp1', status: 'declared',
        declared_at: '2026-10-02T08:05:00Z', decided_at: null, decision_reason: null, eligible: false,
        reasons: [{ code: 'COMPETENCY_NOT_VERIFIED', details: { service_id: 's2', status: 'declared' } }],
      },
      {
        service_id: 's3', w_id: 'W080', name: 'Rozetes nomaiņa', specialisation_id: 'sp2', status: 'rejected',
        declared_at: '2026-10-02T08:05:00Z', decided_at: '2026-10-03T09:00:00Z', decision_reason: 'Nepietiek pieredzes', eligible: false,
        reasons: [{ code: 'QUALIFICATION_MISSING', details: { qualification_id: 'q1', name: 'Elektrodrošības sertifikāts', latest_status: 'verified' } }],
      },
    ],
    qualifications: [
      submission({ id: 'mq1', status: 'verified', document_number: 'EL-1', valid_until: '2026-10-31', submitted_at: '2026-09-01T10:00:00Z', decided_at: '2026-09-02T10:00:00Z', expired: true, files: [{ id: 'f1', mime_type: 'application/pdf', size_bytes: 2048, uploaded_at: '2026-09-01T10:00:00Z' }] }),
      submission({ id: 'mq0', status: 'rejected', document_number: 'EL-0', valid_until: '2027-01-01', submitted_at: '2026-08-01T10:00:00Z', decided_at: '2026-08-02T10:00:00Z', decision_reason: 'Nesalasāms dokuments' }),
      submission({ id: 'mq2', qualification_id: 'q2', qualification_name: 'Darba drošības apmācība', status: 'submitted', files: [{ id: 'f2', mime_type: 'image/png', size_bytes: 4096, uploaded_at: '2026-10-04T10:00:00Z' }] }),
    ],
  }
}

interface Call {
  method: string
  path: string
  search: string
  body: unknown
}

type Override = (call: Call) => Response | Promise<Response> | undefined

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function apiError(status: number, code: string): Response {
  return json({ error: { code, message: 'x', details: {} } }, status)
}

/** A small master backend with the documented rules (withdraw only pending items; reopen; read-only when rejected). */
function serve(caps: Capabilities, override?: Override) {
  const calls: Call[] = []
  let n = 0
  const conflict = (code: string) => apiError(409, code)
  const handle = (call: Call): Response => {
    const writable = caps.approval_status !== 'rejected'
    if (call.method === 'GET' && call.path === '/api/v1/master/capabilities') return json(caps)
    if (call.method === 'GET' && call.path === '/api/v1/master/catalogue') return json(CATALOGUE)
    if (call.method === 'GET' && call.path.startsWith('/api/v1/master/qualifications/')) {
      return new Response(new Blob(['x'], { type: 'image/png' }), { status: 200, headers: { 'Content-Disposition': 'inline; filename="f.png"' } })
    }
    if (call.method !== 'POST') return apiError(404, 'NOT_FOUND')
    if (!writable) return conflict('MASTER_PROFILE_REJECTED')
    const body = call.body as Record<string, string>
    let m: RegExpExecArray | null
    if (call.path === '/api/v1/master/specialisations') {
      const spec = CATALOGUE.specialisations.find((s) => s.id === body.specialisation_id)!
      const row = caps.specialisations.find((s) => s.specialisation_id === spec.id)
      if (row && ['requested', 'approved'].includes(row.status)) return conflict('SPECIALISATION_ALREADY_EXISTS')
      if (row) row.status = 'requested'
      else caps.specialisations.push({ specialisation_id: spec.id, name: spec.name, status: 'requested', requested_at: '2026-11-02T10:00:00Z', decided_at: null, decision_reason: null })
      return json({}, 201)
    }
    if ((m = /^\/api\/v1\/master\/specialisations\/([^/]+)\/withdraw$/.exec(call.path))) {
      const row = caps.specialisations.find((s) => s.specialisation_id === m![1])!
      if (row.status !== 'requested') return conflict('CANNOT_WITHDRAW')
      row.status = 'withdrawn'
      return json({})
    }
    if (call.path === '/api/v1/master/competencies') {
      const row = caps.competencies.find((c) => c.service_id === body.service_id)
      if (row && ['declared', 'verified'].includes(row.status)) return conflict('COMPETENCY_ALREADY_EXISTS')
      if (row) row.status = 'declared'
      else {
        const spec = CATALOGUE.specialisations.find((s) => s.services.some((svc) => svc.id === body.service_id))!
        const svc = spec.services.find((s) => s.id === body.service_id)!
        caps.competencies.push({ service_id: svc.id, w_id: svc.w_id, name: svc.name, specialisation_id: spec.id, status: 'declared', declared_at: '2026-11-02T10:00:00Z', decided_at: null, decision_reason: null, eligible: false, reasons: [] })
      }
      return json({ service_id: body.service_id, status: 'declared' }, 201)
    }
    if ((m = /^\/api\/v1\/master\/competencies\/([^/]+)\/withdraw$/.exec(call.path))) {
      const row = caps.competencies.find((c) => c.service_id === m![1])!
      if (row.status !== 'declared') return conflict('CANNOT_WITHDRAW')
      row.status = 'withdrawn'
      return json({})
    }
    if (call.path === '/api/v1/master/qualifications') {
      const form = call.body as FormData
      const qid = String(form.get('qualification_id'))
      const type = CATALOGUE.qualification_types.find((q) => q.id === qid)!
      const created = submission({
        id: `new${++n}`,
        qualification_id: qid,
        qualification_name: type.name,
        document_number: (form.get('document_number') as string | null) ?? null,
        valid_until: (form.get('valid_until') as string | null) ?? null,
        submitted_at: '2026-11-02T10:00:00Z',
        files: form.getAll('files').map((f, i) => ({ id: `nf${i}`, mime_type: (f as File).type, size_bytes: (f as File).size, uploaded_at: '2026-11-02T10:00:00Z' })),
      })
      caps.qualifications.unshift(created)
      return json(created, 201)
    }
    if ((m = /^\/api\/v1\/master\/qualifications\/([^/]+)\/withdraw$/.exec(call.path))) {
      const row = caps.qualifications.find((s) => s.id === m![1])!
      if (row.status !== 'submitted') return conflict('CANNOT_WITHDRAW')
      row.status = 'withdrawn'
      return json(row)
    }
    return apiError(404, 'NOT_FOUND')
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      const raw = init?.body
      const call: Call = {
        method: init?.method ?? 'GET',
        path: url.pathname,
        search: url.search,
        body: raw instanceof FormData ? raw : raw ? JSON.parse(String(raw)) : undefined,
      }
      calls.push(call)
      return (await override?.(call)) ?? handle(call)
    }),
  )
  return {
    caps,
    calls,
    posts: () => calls.filter((c) => c.method === 'POST'),
    capsLoads: () => calls.filter((c) => c.path === '/api/v1/master/capabilities').length,
  }
}

function renderPage(user: User | null = masterUser, path = '/master/capabilities') {
  return render(
    <AuthContext.Provider value={auth(user)}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

async function loaded() {
  return screen.findByRole('heading', { level: 1, name: 'Manas specializācijas' })
}

/** A specialisation card (an article named by its heading). */
const spec = (name: string) => screen.getByRole('article', { name })
/** The head of a specialisation card: its own status, decision and actions (without its services). */
const head = (name: string) => spec(name).querySelector('header') as HTMLElement
/** A service row (competency) by W-ID, wherever it is shown. */
function service(wId: string) {
  return screen.getByText(wId, { selector: 'code' }).closest('li') as HTMLElement
}
/** The (first) block of a qualification type. */
function qual(name: string) {
  return screen.getAllByText(name, { selector: 'strong' })[0].closest('li') as HTMLElement
}
function rows(list: HTMLElement) {
  return within(list).getAllByRole('listitem').filter((li) => li.parentElement === list)
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:fikso/1') as unknown as typeof URL.createObjectURL
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// --- structure ---------------------------------------------------------------------------------------------------

describe('master capabilities: specialisation cards', () => {
  it('loads the own data from the master API only and shows one card per specialisation', async () => {
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    expect(io.calls.map((c) => c.path).sort()).toEqual(['/api/v1/master/capabilities', '/api/v1/master/catalogue'])
    expect(screen.getByText(/Jūsu profils gaida administratora apstiprinājumu/)).toBeTruthy()
    const list = screen.getByRole('list', { name: 'Manas specializācijas' })
    // Pending and approved first, the rejected one last (display order only).
    expect(rows(list).map((li) => within(li).getByRole('heading', { level: 2 }).textContent)).toEqual([
      'Elektriķis',
      'Santehniķis',
      'Jumiķis',
    ])
    expect(within(head('Elektriķis')).getByText('pieteikta')).toBeTruthy()
    expect(within(head('Santehniķis')).getByText('apstiprināta')).toBeTruthy()
    expect(within(head('Jumiķis')).getByText('noraidīta')).toBeTruthy()
    expect(within(spec('Jumiķis')).getByText(/Iemesls: Nav pieredzes/)).toBeTruthy()
  })

  it('shows each service inside its specialisation with status and eligibility reasons', async () => {
    serve(initialCaps())
    renderPage()
    await loaded()
    const plumbing = within(spec('Santehniķis')).getByRole('list', { name: 'Pakalpojumi: Santehniķis' })
    expect(rows(plumbing).map((li) => li.querySelector('code')?.textContent)).toEqual(['W071', 'W072'])
    expect(within(service('W071')).getByText('Varat saņemt šī pakalpojuma pasūtījumus.')).toBeTruthy()
    expect(within(service('W072')).getByText('pieteikta')).toBeTruthy()
    const electric = within(spec('Elektriķis'))
    expect(electric.getByText('W080', { selector: 'code' })).toBeTruthy()
    const missing = within(service('W080')).getByRole('list', { name: /Kāpēc jūs vēl nesaņemat.*W080/ })
    expect(missing.textContent).toBe('Nav apstiprinātas nepieciešamās kvalifikācijas: Elektrodrošības sertifikāts')
    expect(within(spec('Jumiķis')).getByText('Šai specializācijai vēl nav pieteiktu pakalpojumu.')).toBeTruthy()
  })

  it('shows qualification documents only where the catalogue requires them, and says for what', async () => {
    serve(initialCaps())
    renderPage()
    await loaded()
    const electric = within(spec('Elektriķis'))
    expect(electric.getByText('Kvalifikācijas dokumenti')).toBeTruthy()
    expect(electric.getByText('Nepieciešama visiem šīs specializācijas pakalpojumiem.')).toBeTruthy()
    expect(electric.getByText('Elektrodrošības sertifikāts', { selector: 'strong' })).toBeTruthy()
    const plumbing = within(spec('Santehniķis'))
    expect(plumbing.getByText('Nepieciešama pakalpojumiem: W071')).toBeTruthy()
    expect(plumbing.getByText('Darba drošības apmācība', { selector: 'strong' })).toBeTruthy()
    // No requirement: no documents block at all.
    expect(within(spec('Jumiķis')).queryByText('Kvalifikācijas dokumenti')).toBeNull()
  })

  it('keeps unlinked qualification types and old history in a collapsed "Citas kvalifikācijas" block', async () => {
    const caps = initialCaps()
    caps.qualifications.push(submission({ id: 'old', qualification_id: 'q9', qualification_name: 'Vecā atļauja', status: 'rejected', decided_at: '2026-01-02T10:00:00Z', decision_reason: 'Nederīga' }))
    serve(caps)
    renderPage()
    await loaded()
    const other = screen.getByText('Citas kvalifikācijas (2)').closest('details') as HTMLDetailsElement
    expect(other.open).toBe(false)
    const list = within(other).getByRole('list', { name: 'Citas kvalifikācijas' })
    expect(rows(list).map((li) => li.querySelector('strong')?.textContent)).toEqual(['Augstuma darbu apliecība', 'Vecā atļauja'])
    expect(within(qual('Vecā atļauja')).getByText('Šai kvalifikācijai iesniegumus pašlaik nepieņem.')).toBeTruthy()
    expect(within(qual('Vecā atļauja')).getByText(/Nederīga/)).toBeTruthy()
    expect(within(qual('Vecā atļauja')).queryByRole('button', { name: /Iesniegt/ })).toBeNull()
    expect(within(qual('Augstuma darbu apliecība')).getByRole('button', { name: 'Iesniegt kvalifikāciju: Augstuma darbu apliecība' })).toBeTruthy()
  })

  it('shows the latest submission and keeps the earlier ones one click away', async () => {
    serve(initialCaps())
    renderPage()
    await loaded()
    const history = within(qual('Elektrodrošības sertifikāts')).getByRole('list', { name: 'Iesniegumu vēsture: Elektrodrošības sertifikāts' })
    const latest = rows(history)[0]
    expect(within(latest).getByText('apstiprināta')).toBeTruthy()
    expect(within(latest).getByText('Derīguma termiņš ir beidzies')).toBeTruthy()
    expect(within(latest).getByText('31.10.2026')).toBeTruthy()
    const older = within(history).getByText('Iepriekšējie iesniegumi (1)').closest('details') as HTMLDetailsElement
    expect(older.open).toBe(false)
    const olderList = within(older).getByRole('list', { name: 'Iepriekšējie iesniegumi: Elektrodrošības sertifikāts' })
    expect(within(olderList).getByText('noraidīta')).toBeTruthy()
    expect(within(olderList).getByText(/Nesalasāms dokuments/)).toBeTruthy()
  })

  it('shows an empty state with the way to start', async () => {
    serve({ ...initialCaps(), specialisations: [], competencies: [], qualifications: [] })
    renderPage()
    await loaded()
    expect(screen.getByText('Jūs vēl neesat pieteicis nevienu specializāciju.')).toBeTruthy()
    expect(screen.getByText(/Sāciet ar “\+ Pievienot specializāciju”/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '+ Pievienot specializāciju' })).toBeTruthy()
  })

  it('shows a load error in Latvian and retries', async () => {
    let fail = true
    serve(initialCaps(), (call) => (fail && call.path === '/api/v1/master/capabilities' ? new Response('down', { status: 502 }) : undefined))
    renderPage()
    expect((await screen.findByRole('alert')).textContent).toContain('Radās kļūda. Mēģiniet vēlreiz.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Mēģināt vēlreiz' }))
    await loaded()
  })
})

// --- specialisations ---------------------------------------------------------------------------------------------

describe('master capabilities: specialisations', () => {
  async function openAdd() {
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: '+ Pievienot specializāciju' }))
    return screen.getByRole('alertdialog', { name: 'Pievienot specializāciju' })
  }

  it('adds a specialisation from the catalogue in a dialog and shows its new card', async () => {
    const io = serve(initialCaps())
    renderPage()
    const dialog = await openAdd()
    const select = within(dialog).getByLabelText('Specializācija')
    // Only specialisations without an application; planned ones are marked.
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Izvēlieties…', 'Flīzētājs (plānots)'])
    const send = within(dialog).getByRole('button', { name: 'Pieteikt' })
    expect(send).toHaveProperty('disabled', true) // nothing chosen yet
    expect(send.className).not.toContain('button-danger') // an ordinary submission, not a dangerous one
    await userEvent.selectOptions(select, 'sp3')
    await userEvent.click(send)
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(within(head('Flīzētājs')).getByText('pieteikta')).toBeTruthy()
    expect(screen.getByText('Saglabāts.')).toBeTruthy()
    expect(io.posts()).toEqual([{ method: 'POST', path: '/api/v1/master/specialisations', search: '', body: { specialisation_id: 'sp3' } }])
    expect(io.capsLoads()).toBe(2)
  })

  it('cancelling the dialog sends nothing; an error keeps it open with the message', async () => {
    const io = serve(initialCaps(), (call) => (call.method === 'POST' ? apiError(409, 'SPECIALISATION_NOT_AVAILABLE') : undefined))
    renderPage()
    let dialog = await openAdd()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Atcelt' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(io.posts()).toHaveLength(0)
    dialog = await openAdd()
    await userEvent.selectOptions(within(dialog).getByLabelText('Specializācija'), 'sp3')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pieteikt' }))
    expect((await within(dialog).findByRole('alert')).textContent).toBe('Šī specializācija katalogā vairs netiek piedāvāta.')
    expect(screen.getByRole('alertdialog')).toBeTruthy()
  })

  it('says when every catalogue specialisation is already requested', async () => {
    const caps = initialCaps()
    caps.specialisations.push({ specialisation_id: 'sp3', name: 'Flīzētājs', status: 'requested', requested_at: '2026-10-02T08:00:00Z', decided_at: null, decision_reason: null })
    serve(caps)
    renderPage()
    const dialog = await openAdd()
    expect(within(dialog).getByText('Visas pieejamās specializācijas jau ir pieteiktas.')).toBeTruthy()
    expect(within(dialog).getByRole('button', { name: 'Pieteikt' })).toHaveProperty('disabled', true)
  })

  it('withdraws only a pending specialisation, after a confirmation, and may request it again', async () => {
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    // Approved: only an admin changes it. Rejected but no longer offered: nothing to request again.
    expect(within(head('Santehniķis')).queryByRole('button')).toBeNull()
    expect(within(spec('Jumiķis')).queryByRole('button')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt pieteikumu: Elektriķis' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Atsaukt pieteikumu?' })
    expect(dialog.textContent).toContain('Pieteikums “Elektriķis” vairs netiks izskatīts')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Atcelt' }))
    expect(io.posts()).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt pieteikumu: Elektriķis' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Atsaukt' }))
    await waitFor(() => expect(within(head('Elektriķis')).getByText('atsaukta pēc meistara lūguma')).toBeTruthy())
    expect(io.posts().map((c) => c.path)).toEqual(['/api/v1/master/specialisations/sp2/withdraw'])
    expect(document.activeElement).toBe(document.getElementById('main')) // the withdraw button is gone
    // A withdrawn specialisation offers no new services until it is requested again.
    expect(within(spec('Elektriķis')).getByText('Pakalpojumus var pieteikt, kad specializācija ir pieteikta vai apstiprināta.')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: 'Pieteikt atkārtoti: Elektriķis' }))
    await waitFor(() => expect(within(head('Elektriķis')).getByText('pieteikta')).toBeTruthy())
    expect(io.posts()[1]).toMatchObject({ path: '/api/v1/master/specialisations', body: { specialisation_id: 'sp2' } })
  })

  it.each([
    ['CANNOT_WITHDRAW', 409, 'Atsaukt var tikai pieteikumus, kas vēl gaida lēmumu.', 2],
    ['RATE_LIMITED', 429, 'Pārāk daudz mēģinājumu. Mēģiniet vēlāk.', 1],
    ['SOMETHING_NEW', 500, 'Radās kļūda. Mēģiniet vēlreiz.', 1],
  ])('reports %s at the card in Latvian (a conflict re-reads the data)', async (code, status, text, loads) => {
    const io = serve(initialCaps(), (call) => (call.method === 'POST' ? apiError(status, code) : undefined))
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt pieteikumu: Elektriķis' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Atsaukt' }))
    expect((await within(head('Elektriķis')).findByRole('alert')).textContent).toBe(text)
    await waitFor(() => expect(io.capsLoads()).toBe(loads))
  })

  it('two withdrawal confirmations in the same tick send one request', async () => {
    let release: (r: Response) => void = () => {}
    const io = serve(initialCaps(), (call) => (call.method === 'POST' ? new Promise<Response>((r) => (release = r)) : undefined))
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt pieteikumu: Elektriķis' }))
    const confirm = within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Atsaukt' })
    act(() => {
      confirm.click()
      confirm.click()
    })
    await waitFor(() => expect(io.posts()).toHaveLength(1))
    await act(async () => release(json({})))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(io.posts()).toHaveLength(1)
  })
})

// --- services (competencies) -------------------------------------------------------------------------------------

describe('master capabilities: services', () => {
  it('adds a service inside its specialisation (only its own undeclared services)', async () => {
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    const plumbing = within(spec('Santehniķis'))
    await userEvent.click(plumbing.getByRole('button', { name: '+ Pievienot pakalpojumu: Santehniķis' }))
    const form = plumbing.getByRole('form', { name: '+ Pievienot pakalpojumu: Santehniķis' })
    const select = within(form).getByLabelText('Pakalpojums')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Izvēlieties…', 'W075 Ūdens sildītāja pieslēgšana (plānots)'])
    await userEvent.selectOptions(select, 's5')
    await userEvent.click(within(form).getByRole('button', { name: 'Pieteikt' }))
    await waitFor(() => expect(within(service('W075')).getByText('pieteikta')).toBeTruthy())
    expect(within(spec('Santehniķis')).getByText('W075', { selector: 'code' })).toBeTruthy()
    expect(io.posts()).toEqual([{ method: 'POST', path: '/api/v1/master/competencies', search: '', body: { service_id: 's5' } }])
    // All services of the specialisation are declared now.
    expect(within(spec('Santehniķis')).getByText('Visi šīs specializācijas pakalpojumi jau ir pieteikti.')).toBeTruthy()
  })

  it('offers no new service under a rejected specialisation', async () => {
    serve(initialCaps())
    renderPage()
    await loaded()
    expect(within(spec('Jumiķis')).queryByRole('button', { name: /Pievienot pakalpojumu/ })).toBeNull()
    expect(within(spec('Jumiķis')).getByText('Pakalpojumus var pieteikt, kad specializācija ir pieteikta vai apstiprināta.')).toBeTruthy()
  })

  it('a verified competency offers no action: the master cannot verify or revoke it', async () => {
    serve(initialCaps())
    renderPage()
    await loaded()
    expect(within(service('W071')).queryByRole('button')).toBeNull()
    expect(screen.queryByRole('button', { name: /^Apstiprināt/ })).toBeNull()
  })

  it('withdraws a declared competency and declares a rejected one again (not approved automatically)', async () => {
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Atsaukt pieteikumu: W072 Izlietnes uzstādīšana' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Atsaukt' }))
    await waitFor(() => expect(within(service('W072')).getByText('atsaukta pēc meistara lūguma')).toBeTruthy())
    await userEvent.click(screen.getByRole('button', { name: 'Pieteikt atkārtoti: W080 Rozetes nomaiņa' }))
    await waitFor(() => expect(within(service('W080')).getByText('pieteikta')).toBeTruthy())
    // Pending again; the earlier rejection stays visible as the previous decision.
    expect(within(service('W080')).getByText(/^Iepriekšējais lēmums: .* · Iemesls: Nepietiek pieredzes$/)).toBeTruthy()
    expect(within(service('W071')).getByText(/^Lēmums: /)).toBeTruthy()
    expect(io.posts().map((c) => [c.path, c.body])).toEqual([
      ['/api/v1/master/competencies/s2/withdraw', undefined],
      ['/api/v1/master/competencies', { service_id: 's3' }],
    ])
  })

  it('a double click sends one application and shows the loading state', async () => {
    let release: (r: Response) => void = () => {}
    const io = serve(initialCaps(), (call) => (call.method === 'POST' ? new Promise<Response>((r) => (release = r)) : undefined))
    renderPage()
    await loaded()
    const again = screen.getByRole('button', { name: 'Pieteikt atkārtoti: W080 Rozetes nomaiņa' })
    await userEvent.dblClick(again)
    expect(io.posts()).toHaveLength(1)
    expect(again).toHaveProperty('disabled', true)
    expect(again.getAttribute('aria-busy')).toBe('true')
    expect(screen.getByRole('button', { name: 'Atsaukt pieteikumu: Elektriķis' })).toHaveProperty('disabled', true)
    await act(async () => release(json({ service_id: 's3', status: 'declared' }, 201)))
    expect(await screen.findByText('Saglabāts.')).toBeTruthy()
    expect(io.posts()).toHaveLength(1)
  })
})

// --- qualifications ----------------------------------------------------------------------------------------------

describe('master capabilities: qualification documents', () => {
  async function openForm(name: string) {
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: `Iesniegt jaunu dokumentu: ${name}` }))
    return screen.getByRole('form', { name: `Iesniegt kvalifikāciju: ${name}` })
  }

  const pdf = (name = 'sertifikats.pdf', size = 2048) => {
    const file = new File(['%PDF-1.7'], name, { type: 'application/pdf' })
    Object.defineProperty(file, 'size', { value: size })
    return file
  }

  it('resubmits after expiry inside the card: multipart with the fields and files, history kept', async () => {
    const io = serve(initialCaps())
    renderPage()
    const form = await openForm('Elektrodrošības sertifikāts')
    expect(within(spec('Elektriķis')).getByRole('form', { name: 'Iesniegt kvalifikāciju: Elektrodrošības sertifikāts' })).toBe(form)
    await userEvent.type(within(form).getByLabelText('Dokumenta numurs (obligāts)'), '  EL-2  ')
    await userEvent.type(within(form).getByLabelText('Derīga līdz (obligāts)'), '2028-05-31')
    expect(within(form).getByLabelText('Derīga līdz (obligāts)').getAttribute('min')).toBe('2026-11-02')
    expect(within(form).getByText('Ne ilgāk kā 60 mēneši no šodienas.')).toBeTruthy()
    await userEvent.upload(within(form).getByLabelText(/Dokumenti \(PDF/), [pdf('a.pdf'), pdf('b.pdf')])
    expect(within(form).getByRole('list', { name: 'Izvēlētie faili' }).textContent).toContain('a.pdf')
    await userEvent.click(within(form).getByRole('button', { name: 'Iesniegt' }))

    expect(await screen.findByText('Kvalifikācija iesniegta. Administrators to izskatīs.')).toBeTruthy()
    const [post] = io.posts()
    expect(post.path).toBe('/api/v1/master/qualifications')
    const sent = post.body as FormData
    expect(sent.get('qualification_id')).toBe('q1')
    expect(sent.get('document_number')).toBe('EL-2')
    expect(sent.get('valid_until')).toBe('2028-05-31')
    expect(sent.getAll('files').map((f) => (f as File).name)).toEqual(['a.pdf', 'b.pdf'])

    const history = within(qual('Elektrodrošības sertifikāts')).getByRole('list', { name: 'Iesniegumu vēsture: Elektrodrošības sertifikāts' })
    expect(within(rows(history)[0]).getByText('iesniegta')).toBeTruthy()
    const older = within(history).getByRole('list', { name: 'Iepriekšējie iesniegumi: Elektrodrošības sertifikāts' })
    expect(rows(older).map((r) => r.querySelector('.badge')?.textContent)).toEqual(['apstiprināta', 'noraidīta'])
    expect(within(qual('Elektrodrošības sertifikāts')).getByText('Iesniegums gaida administratora lēmumu.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Iesniegt jaunu dokumentu: Elektrodrošības/ })).toBeNull()
  })

  it('sends no optional field that is empty', async () => {
    const io = serve({ ...initialCaps(), qualifications: [] })
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Iesniegt kvalifikāciju: Darba drošības apmācība' }))
    const form = screen.getByRole('form', { name: 'Iesniegt kvalifikāciju: Darba drošības apmācība' })
    await userEvent.upload(within(form).getByLabelText(/Dokumenti/), pdf())
    await userEvent.click(within(form).getByRole('button', { name: 'Iesniegt' }))
    await screen.findByText('Kvalifikācija iesniegta. Administrators to izskatīs.')
    const sent = io.posts()[0].body as FormData
    expect(sent.get('qualification_id')).toBe('q2')
    expect(sent.getAll('files')).toHaveLength(1)
    expect(sent.has('document_number')).toBe(false)
    expect(sent.has('valid_until')).toBe(false)
  })

  it('asks for the fields the qualification type requires before sending', async () => {
    const io = serve(initialCaps())
    renderPage()
    const form = await openForm('Elektrodrošības sertifikāts')
    await userEvent.click(within(form).getByRole('button', { name: 'Iesniegt' }))
    expect(within(form).getByRole('alert').textContent).toBe(
      'Pievienojiet vismaz vienu dokumentu.Norādiet dokumenta numuru.Norādiet derīguma termiņu.',
    )
    expect(io.posts()).toHaveLength(0)
  })

  it.each([
    ['too many files', () => Array.from({ length: 6 }, (_, i) => pdf(`f${i}.pdf`)), 'Vienā iesniegumā var būt ne vairāk kā 5 faili.'],
    ['a file over 10 MB', () => [pdf('liels.pdf', 10 * 1024 * 1024 + 1)], 'Fails “liels.pdf” ir lielāks par 10 MB.'],
    ['an empty file', () => [pdf('tukss.pdf', 0)], 'Fails “tukss.pdf” ir tukšs.'],
    ['a wrong type', () => [new File(['x'], 'teksts.txt', { type: 'text/plain' })], 'Faila “teksts.txt” formāts nav atļauts. Atļauti: PDF, JPEG, PNG, WebP, HEIC.'],
  ])('refuses %s before sending', async (_name, files, text) => {
    const io = serve(initialCaps())
    renderPage()
    const form = await openForm('Elektrodrošības sertifikāts')
    const user = userEvent.setup({ applyAccept: false })
    await user.upload(within(form).getByLabelText(/Dokumenti \(PDF/), files())
    expect(within(form).getByRole('alert').textContent).toContain(text)
    expect(within(form).getByRole('button', { name: 'Iesniegt' })).toHaveProperty('disabled', true)
    expect(io.posts()).toHaveLength(0)
  })

  it('accepts exactly 10 MB, a HEIC without a browser type, and recovers after removing a bad file', async () => {
    serve(initialCaps())
    renderPage()
    const form = await openForm('Elektrodrošības sertifikāts')
    const user = userEvent.setup({ applyAccept: false })
    const heic = new File(['x'], 'foto.HEIC', { type: '' })
    await user.upload(within(form).getByLabelText(/Dokumenti \(PDF/), [pdf('max.pdf', 10 * 1024 * 1024), heic, new File(['x'], 'a.txt', { type: 'text/plain' })])
    expect(within(form).getByRole('alert').textContent).toBe('Faila “a.txt” formāts nav atļauts. Atļauti: PDF, JPEG, PNG, WebP, HEIC.')
    await user.click(within(form).getByRole('button', { name: 'Noņemt a.txt' }))
    expect(within(form).queryByRole('alert')).toBeNull()
    expect(within(form).getByRole('button', { name: 'Iesniegt' })).toHaveProperty('disabled', false)
  })

  it.each([
    ['UNSUPPORTED_FILE_TYPE', 422, 'Faila saturs neatbilst atļautajiem formātiem (PDF, JPEG, PNG, WebP, HEIC).', 1],
    ['FILE_TOO_LARGE', 413, 'Katrs fails drīkst būt ne lielāks par 10 MB.', 1],
    ['VALIDITY_TOO_LONG', 422, 'Derīguma termiņš ir garāks, nekā šai kvalifikācijai atļauts.', 1],
    ['VALID_UNTIL_IN_PAST', 422, 'Dokumenta derīguma termiņš jau ir beidzies.', 1],
    ['QUALIFICATION_STILL_VALID', 409, 'Kvalifikācija vēl ir derīga — jaunu dokumentu varēs iesniegt pēc termiņa beigām.', 2],
    ['RATE_LIMITED', 429, 'Pārāk daudz mēģinājumu. Mēģiniet vēlāk.', 1],
  ])('shows the backend refusal %s and keeps the form', async (code, status, text, loads) => {
    const io = serve(initialCaps(), (call) => (call.method === 'POST' ? apiError(status, code) : undefined))
    renderPage()
    const form = await openForm('Elektrodrošības sertifikāts')
    await userEvent.type(within(form).getByLabelText('Dokumenta numurs (obligāts)'), 'EL-2')
    await userEvent.type(within(form).getByLabelText('Derīga līdz (obligāts)'), '2028-05-31')
    await userEvent.upload(within(form).getByLabelText(/Dokumenti/), pdf())
    await userEvent.click(within(form).getByRole('button', { name: 'Iesniegt' }))
    expect((await within(qual('Elektrodrošības sertifikāts')).findByText(text)).getAttribute('role')).toBe('alert')
    await waitFor(() => expect(io.capsLoads()).toBe(loads))
    expect((within(form).getByLabelText('Dokumenta numurs (obligāts)') as HTMLInputElement).value).toBe('EL-2')
  })

  it('a pending submission blocks a new one and can be withdrawn after a confirmation', async () => {
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    const q2 = qual('Darba drošības apmācība')
    expect(within(q2).getByText('Iesniegums gaida administratora lēmumu.')).toBeTruthy()
    expect(within(q2).queryByRole('button', { name: /Iesniegt/ })).toBeNull()
    await userEvent.click(within(q2).getByRole('button', { name: 'Atsaukt pieteikumu: Darba drošības apmācība' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Atsaukt' }))
    await waitFor(() => expect(within(qual('Darba drošības apmācība')).getByText('atsaukta pēc meistara lūguma')).toBeTruthy())
    expect(io.posts().map((c) => c.path)).toEqual(['/api/v1/master/qualifications/mq2/withdraw'])
    // After the withdrawal a new submission is possible; the withdrawn one stays in the history.
    expect(screen.getByRole('button', { name: 'Iesniegt jaunu dokumentu: Darba drošības apmācība' })).toBeTruthy()
  })

  it('a still valid verified qualification can be neither changed, withdrawn nor replaced', async () => {
    const caps = initialCaps()
    caps.qualifications[0] = { ...caps.qualifications[0], valid_until: '2026-11-20', expired: false, expires_soon: true }
    serve(caps)
    renderPage()
    await loaded()
    const q1 = qual('Elektrodrošības sertifikāts')
    expect(within(q1).getByText(/apstiprināta un derīga līdz 20\.11\.2026.*Derīguma termiņš beigsies 20\.11\.2026/)).toBeTruthy()
    expect(within(q1).queryByRole('button', { name: /Iesniegt|Atsaukt/ })).toBeNull()
    expect(within(q1).getByText('Derīguma termiņš drīz beigsies')).toBeTruthy()
  })

  it('a double click on submit sends one multipart request', async () => {
    let release: (r: Response) => void = () => {}
    const io = serve({ ...initialCaps(), qualifications: [] }, (call) => (call.method === 'POST' ? new Promise<Response>((r) => (release = r)) : undefined))
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Iesniegt kvalifikāciju: Darba drošības apmācība' }))
    const form = screen.getByRole('form', { name: 'Iesniegt kvalifikāciju: Darba drošības apmācība' })
    await userEvent.upload(within(form).getByLabelText(/Dokumenti/), pdf())
    const send = within(form).getByRole('button', { name: 'Iesniegt' })
    await userEvent.dblClick(send)
    expect(io.posts()).toHaveLength(1)
    expect(send).toHaveProperty('disabled', true)
    expect(send.getAttribute('aria-busy')).toBe('true')
    await act(async () => release(json(submission({ id: 'x', qualification_id: 'q2' }), 201)))
    expect(await screen.findByText('Kvalifikācija iesniegta. Administrators to izskatīs.')).toBeTruthy()
    expect(io.posts()).toHaveLength(1)
  })
})

// --- documents ---------------------------------------------------------------------------------------------------

describe('master capabilities: own documents', () => {
  it('views an own image and downloads an own PDF through the master route only', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const io = serve(initialCaps())
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Skatīt: Dokuments 1 (Darba drošības apmācība)' }))
    expect((await screen.findByRole('img', { name: 'Dokumenta skats' })).getAttribute('src')).toBe('blob:fikso/1')
    expect(screen.queryByRole('button', { name: 'Skatīt: Dokuments 1 (Elektrodrošības sertifikāts)' })).toBeNull() // PDF
    await userEvent.click(screen.getByRole('button', { name: 'Lejupielādēt: Dokuments 1 (Elektrodrošības sertifikāts)' }))
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    const files = io.calls.filter((c) => c.path.includes('/files/'))
    expect(files.map((c) => `${c.path}${c.search}`)).toEqual([
      '/api/v1/master/qualifications/mq2/files/f2?mode=view',
      '/api/v1/master/qualifications/mq1/files/f1?mode=download',
    ])
    expect(io.calls.some((c) => c.path.startsWith('/api/v1/admin'))).toBe(false)
  })

  it('reports a file that is not the master’s own as not found', async () => {
    serve(initialCaps(), (call) => (call.path.includes('/files/') ? apiError(404, 'FILE_NOT_FOUND') : undefined))
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Skatīt: Dokuments 1 (Darba drošības apmācība)' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Dokuments nav atrasts.')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })
})

// --- rejected profile --------------------------------------------------------------------------------------------

describe('master capabilities: rejected profile', () => {
  it('is read-only with a Latvian explanation; history and documents stay visible', async () => {
    const io = serve(initialCaps('rejected'))
    renderPage()
    await loaded()
    const notice = screen.getByText(/Jūsu profils ir noraidīts/).closest('.notice') as HTMLElement
    expect(notice.textContent).toContain('nepieciešams administratora lēmums')
    expect(notice.textContent).toContain('Noraidīšanas iemesls: Nepilni dati')
    expect(screen.queryByRole('button', { name: /Atsaukt|Pieteikt|Iesniegt|Pievienot/ })).toBeNull()
    expect(screen.queryByText(/Pakalpojumus var pieteikt/)).toBeNull()
    expect(screen.getAllByRole('button', { name: /Skatīt|Lejupielādēt/ }).length).toBeGreaterThan(0)
    expect(within(qual('Elektrodrošības sertifikāts')).getByText(/Nesalasāms dokuments/)).toBeTruthy()
    expect(io.posts()).toHaveLength(0)
  })

  it('a profile rejected meanwhile: the refused change is reported and the page turns read-only', async () => {
    const caps = initialCaps()
    const io = serve(caps, (call) => {
      if (call.method === 'POST') caps.approval_status = 'rejected'
      return undefined
    })
    renderPage()
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Pieteikt atkārtoti: W080 Rozetes nomaiņa' }))
    expect(await screen.findByText(/Jūsu profils ir noraidīts\. Savus datus/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Atsaukt|Pieteikt|Iesniegt|Pievienot/ })).toBeNull()
    expect(caps.competencies[2].status).toBe('rejected')
    expect(io.capsLoads()).toBe(2)
  })
})

// --- roles -------------------------------------------------------------------------------------------------------

describe('master capabilities: roles', () => {
  it.each([
    ['admin', 'Pārskats'],
    ['client', 'Mani pieteikumi'],
  ] as const)('a %s is sent to their own area and nothing is requested', async (role, home) => {
    const io = serve(initialCaps())
    renderPage({ ...masterUser, role, master_approval_status: null })
    expect(await screen.findByRole('heading', { name: home })).toBeTruthy()
    expect(io.calls.filter((c) => c.path.startsWith('/api/v1/master'))).toHaveLength(0)
  })

  it('an anonymous visitor is sent to login', async () => {
    const io = serve(initialCaps())
    renderPage(null)
    expect(await screen.findByRole('button', { name: 'Pieslēgties' })).toBeTruthy()
    expect(io.calls).toHaveLength(0)
  })

  it('the master panel links to the page', async () => {
    serve(initialCaps())
    renderPage(masterUser, '/master')
    await userEvent.click(await screen.findByRole('link', { name: /^Atvērt manas specializācijas/ }))
    await loaded()
  })
})
