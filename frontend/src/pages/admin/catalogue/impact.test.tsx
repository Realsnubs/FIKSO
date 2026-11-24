import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  BasisItem,
  CatalogueTree,
  ImpactResponse,
  TreeCategory,
  TreeService,
  TreeSpecialisation,
} from '../../../types/catalogue'
import { CataloguePage } from './CataloguePage'

// --- fixture ----------------------------------------------------------------------------------------------------

const entry = { description: null, status_reason: null, source: 'admin', source_ref: null, updated_at: '2026-11-01T10:00:00Z' }

function service(id: string, w_id: string, name: string, over: Partial<TreeService> = {}): TreeService {
  return {
    ...entry,
    id,
    name,
    version: 5,
    sort_order: 0,
    specialisation_id: 'sp1',
    w_id,
    status: 'active',
    risk_level: 'normal',
    qualification_required: false,
    restrictions: null,
    review_note: null,
    qualification_ids: [],
    qualifications_ready: true,
    eligible_masters: 2,
    orderable: true,
    orderable_reasons: [],
    ...over,
  }
}

function spec(id: string, category_id: string, name: string, services: TreeService[], version = 4): TreeSpecialisation {
  return {
    ...entry,
    id,
    category_id,
    name,
    version,
    sort_order: 0,
    status: 'active',
    qualification_required: false,
    qualification_ids: [],
    services,
  }
}

function category(id: string, name: string, specialisations: TreeSpecialisation[], version = 3): TreeCategory {
  return { ...entry, id, name, version, sort_order: 0, status: 'active', specialisations }
}

function tree(): CatalogueTree {
  return {
    catalogue_role: 'issuer',
    can_create: true,
    qualifications: [
      {
        id: 'q1',
        name: 'Elektrodrošība',
        description: null,
        status: 'active',
        requires_document: true,
        requires_document_number: false,
        requires_expiry_date: false,
        max_validity_months: null,
        verifier_instructions: null,
        version: 1,
        updated_at: '2026-11-01T10:00:00Z',
      },
    ],
    categories: [
      category('c1', 'Santehnika', [
        spec('sp1', 'c1', 'Izlietņu meistars', [
          service('s1', 'W077', 'Izlietnes uzstādīšana'),
          service('s2', 'W090', 'Augsta riska darbs', { status: 'hold', version: 6, orderable: false }),
        ]),
        spec('sp2', 'c1', 'Krānu meistars', [service('s3', 'W080', 'Krāna maiņa', { specialisation_id: 'sp2' })], 7),
      ]),
      category('c2', 'Elektrība', [spec('sp3', 'c2', 'Elektriķis', [], 8)], 9),
    ],
  }
}

// Every entry of the fixture tree with its version: like the backend, the basis contains the changed entry.
const BASIS: BasisItem[] = [
  { kind: 'category', id: 'c1', version: 3 },
  { kind: 'category', id: 'c2', version: 9 },
  { kind: 'specialisation', id: 'sp1', version: 4 },
  { kind: 'specialisation', id: 'sp2', version: 7 },
  { kind: 'specialisation', id: 'sp3', version: 8 },
  { kind: 'service', id: 's1', version: 5 },
  { kind: 'service', id: 's2', version: 6 },
  { kind: 'service', id: 's3', version: 5 },
]

function preview(over: Partial<ImpactResponse> = {}): ImpactResponse {
  return {
    entity: 'service',
    id: 's1',
    change: { kind: 'status', status: 'inactive', reason: null },
    basis: BASIS,
    services: [
      {
        service_id: 's1',
        w_id: 'W077',
        name: 'Izlietnes uzstādīšana',
        before: { orderable: true, eligible_masters: 2, reasons: [] },
        after: {
          orderable: false,
          eligible_masters: 2,
          reasons: [{ code: 'SERVICE_NOT_ACTIVE', details: { id: 's1', status: 'inactive' } }],
        },
      },
    ],
    stops_being_orderable: ['s1'],
    becomes_orderable: [],
    masters: {
      by_specialisation_status: { approved: 2, requested: 1 },
      by_competency_status: { verified: 2 },
      losing_eligibility: { total: 1, items: [{ master_id: 'm1', full_name: 'Jānis Bērziņš' }] },
    },
    open_requests: null,
    notes: { open_requests: 'x', eligible_masters: 'x' },
    computed_at: '2026-11-02T10:00:00Z',
    ...over,
  }
}

// --- API mock ---------------------------------------------------------------------------------------------------

interface Call {
  url: string
  method: string
  body: Record<string, unknown> | undefined
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

function error(status: number, code: string, details: Record<string, unknown> = {}): Response {
  return json(status, { error: { code, message: 'x', details } })
}

/** Tree GETs always succeed; previews and changes answer from their queues (default: success). */
function mockApi({ previews = [], changes = [] }: { previews?: Response[]; changes?: (Response | Promise<Response>)[] } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url: String(url), method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (method === 'GET') return json(200, tree())
      if (String(url).endsWith('/admin/catalogue/impact')) return previews.shift() ?? json(200, preview())
      return (await changes.shift()) ?? json(200, {})
    }),
  )
  return {
    calls,
    previews: () => calls.filter((c) => c.url.endsWith('/admin/catalogue/impact')),
    changes: () => calls.filter((c) => c.method !== 'GET' && !c.url.endsWith('/admin/catalogue/impact')),
    treeLoads: () => calls.filter((c) => c.method === 'GET').length,
  }
}

afterEach(() => vi.unstubAllGlobals())

async function open(): Promise<UserEvent> {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <CataloguePage />
    </MemoryRouter>,
  )
  await screen.findByText('W077')
  return user
}

const row = (text: string) => screen.getByText(text).closest('li') as HTMLElement

async function changeStatus(user: UserEvent, text: string, status: string) {
  const li = row(text)
  await user.click(within(li).getAllByRole('button', { name: 'Statuss' })[0])
  await user.selectOptions(within(li).getAllByLabelText('Jaunais statuss')[0], status)
  await user.click(within(li).getAllByRole('button', { name: 'Mainīt statusu' })[0])
}

async function edit(user: UserEvent, text: string, change: (form: HTMLElement) => Promise<void>) {
  const li = row(text)
  await user.click(within(li).getAllByRole('button', { name: 'Labot' })[0])
  const form = within(li).getAllByRole('button', { name: 'Saglabāt' })[0].closest('form') as HTMLElement
  await change(form)
  await user.click(within(form).getByRole('button', { name: 'Saglabāt' }))
}

async function setRequirements(user: UserEvent, text: string) {
  const li = row(text)
  await user.click(within(li).getAllByRole('button', { name: 'Nepieciešamās kvalifikācijas' })[0])
  await user.click(within(li).getByLabelText(/Elektrodrošība/))
  await user.click(within(li).getByRole('button', { name: 'Saglabāt prasības' }))
}

const dialog = () => screen.findByRole('dialog', { name: 'Izmaiņu sekas' })
const confirmButton = async () => within(await dialog()).findByRole('button', { name: 'Apstiprināt' })

// --- the ten changes ----------------------------------------------------------------------------------------------

type Case = [
  string,
  (user: UserEvent) => Promise<void>,
  Record<string, unknown>, // the preview request
  string, // the change URL
  string, // the change method
  Record<string, unknown>, // the change body (without expected_basis)
]

const CASES: Case[] = [
  [
    'category status',
    (user) => changeStatus(user, 'Santehnika', 'inactive'),
    { entity: 'category', id: 'c1', change: { kind: 'status', status: 'inactive', reason: null } },
    '/api/v1/admin/catalogue/categories/c1/status',
    'POST',
    { status: 'inactive', reason: null, expected_version: 3 },
  ],
  [
    'specialisation status',
    (user) => changeStatus(user, 'Izlietņu meistars', 'planned'),
    { entity: 'specialisation', id: 'sp1', change: { kind: 'status', status: 'planned', reason: null } },
    '/api/v1/admin/catalogue/specialisations/sp1/status',
    'POST',
    { status: 'planned', reason: null, expected_version: 4 },
  ],
  [
    'specialisation move',
    (user) =>
      edit(user, 'Izlietņu meistars', async (form) => {
        await user.selectOptions(within(form).getByLabelText('Kategorija'), 'c2')
      }),
    { entity: 'specialisation', id: 'sp1', change: { kind: 'move', target_id: 'c2' } },
    '/api/v1/admin/catalogue/specialisations/sp1',
    'PATCH',
    { name: 'Izlietņu meistars', description: null, category_id: 'c2', qualification_required: false, expected_version: 4 },
  ],
  [
    'specialisation qualification_required',
    (user) =>
      edit(user, 'Izlietņu meistars', async (form) => {
        await user.click(within(form).getByLabelText(/Nepieciešama kvalifikācija/))
      }),
    { entity: 'specialisation', id: 'sp1', change: { kind: 'qualification_required', value: true } },
    '/api/v1/admin/catalogue/specialisations/sp1',
    'PATCH',
    { name: 'Izlietņu meistars', description: null, category_id: 'c1', qualification_required: true, expected_version: 4 },
  ],
  [
    'specialisation requirements',
    (user) => setRequirements(user, 'Izlietņu meistars'),
    { entity: 'specialisation', id: 'sp1', change: { kind: 'requirements', qualification_ids: ['q1'] } },
    '/api/v1/admin/catalogue/specialisations/sp1/qualifications',
    'PUT',
    { qualification_ids: ['q1'], expected_version: 4 },
  ],
  [
    'service status',
    (user) => changeStatus(user, 'W077', 'inactive'),
    { entity: 'service', id: 's1', change: { kind: 'status', status: 'inactive', reason: null } },
    '/api/v1/admin/catalogue/services/s1/status',
    'POST',
    { status: 'inactive', reason: null, expected_version: 5 },
  ],
  [
    'service move',
    (user) =>
      edit(user, 'W077', async (form) => {
        await user.selectOptions(within(form).getByLabelText('Specializācija'), 'sp2')
      }),
    { entity: 'service', id: 's1', change: { kind: 'move', target_id: 'sp2' } },
    '/api/v1/admin/catalogue/services/s1',
    'PATCH',
    { specialisation_id: 'sp2', qualification_required: false, expected_version: 5 },
  ],
  [
    'service qualification_required',
    (user) =>
      edit(user, 'W077', async (form) => {
        await user.click(within(form).getByLabelText('Nepieciešama kvalifikācija'))
      }),
    { entity: 'service', id: 's1', change: { kind: 'qualification_required', value: true } },
    '/api/v1/admin/catalogue/services/s1',
    'PATCH',
    { specialisation_id: 'sp1', qualification_required: true, expected_version: 5 },
  ],
  [
    'service requirements',
    (user) => setRequirements(user, 'W077'),
    { entity: 'service', id: 's1', change: { kind: 'requirements', qualification_ids: ['q1'] } },
    '/api/v1/admin/catalogue/services/s1/qualifications',
    'PUT',
    { qualification_ids: ['q1'], expected_version: 5 },
  ],
  [
    'HOLD activation',
    async (user) => {
      const li = row('W090')
      await user.click(within(li).getByRole('button', { name: 'Statuss' }))
      await user.click(within(li).getByLabelText(/Apstiprinu, ka šo augsta riska pakalpojumu/))
      const holdForm = within(li).getByRole('button', { name: 'Aktivizēt HOLD pakalpojumu' }).closest('form') as HTMLElement
      await user.type(within(holdForm).getByLabelText('Iemesls'), 'Pārbaudīts')
      await user.click(within(holdForm).getByRole('button', { name: 'Aktivizēt HOLD pakalpojumu' }))
    },
    { entity: 'service', id: 's2', change: { kind: 'activate_hold', reason: 'Pārbaudīts' } },
    '/api/v1/admin/catalogue/services/s2/activate-hold',
    'POST',
    { confirm: true, reason: 'Pārbaudīts', expected_version: 6 },
  ],
]

describe('impact preview before every availability change (step 4.6.3)', () => {
  it.each(CASES)('%s: preview first, then the change with the basis', async (_name, act, request, url, method, body) => {
    const api = mockApi()
    const user = await open()
    await act(user)

    await dialog()
    expect(api.previews().map((c) => c.body)).toEqual([request])
    expect(api.changes()).toEqual([]) // nothing is applied before the admin confirms

    await user.click(await confirmButton())
    await waitFor(() => expect(api.changes()).toHaveLength(1))
    const [sent] = api.changes()
    expect([sent.url, sent.method]).toEqual([url, method])
    expect(sent.body).toMatchObject(body)
    expect(sent.body?.expected_basis).toEqual(BASIS) // the complete basis of the preview
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.treeLoads()).toBe(2) // reloaded only after the successful change
  })

  it('saves a name change directly, with the version and without a preview', async () => {
    const api = mockApi()
    const user = await open()
    await edit(user, 'W077', async (form) => {
      const name = within(form).getByLabelText('Nosaukums')
      await user.clear(name)
      await user.type(name, 'Jauns nosaukums')
    })
    await waitFor(() => expect(api.changes()).toHaveLength(1))
    expect(api.previews()).toEqual([])
    const [sent] = api.changes()
    expect(sent.body).toMatchObject({ name: 'Jauns nosaukums', expected_version: 5 })
    expect('expected_basis' in (sent.body ?? {})).toBe(false)
  })

  it('asks for a move and a flag change to be saved separately', async () => {
    const api = mockApi()
    const user = await open()
    await edit(user, 'W077', async (form) => {
      await user.selectOptions(within(form).getByLabelText('Specializācija'), 'sp2')
      await user.click(within(form).getByLabelText('Nepieciešama kvalifikācija'))
    })
    expect(await screen.findByText(/saglabājiet atsevišķi/)).toBeTruthy()
    expect(api.previews()).toEqual([])
    expect(api.changes()).toEqual([])
    // The form stays open with what the admin entered, so one of the two can be undone and saved.
    const li = row('W077')
    expect((within(li).getByLabelText('Specializācija') as HTMLSelectElement).value).toBe('sp2')
    expect((within(li).getByLabelText('Nepieciešama kvalifikācija') as HTMLInputElement).checked).toBe(true)
  })
})

// --- conflicts and errors -------------------------------------------------------------------------------------------

describe('impact dialog conflicts and errors', () => {
  it('after IMPACT_PREVIEW_OUTDATED loads a new preview and waits for a new confirmation', async () => {
    // Someone changed the service itself: the new preview carries its new version.
    const fresh: BasisItem[] = BASIS.map((item) => (item.id === 's1' ? { ...item, version: 6 } : item))
    const api = mockApi({
      previews: [json(200, preview()), json(200, preview({ basis: fresh }))],
      changes: [error(409, 'IMPACT_PREVIEW_OUTDATED', { changed: [], added: [], removed: [] })],
    })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    await user.click(await confirmButton())

    expect(await within(await dialog()).findByText(/Kataloga dati kopš priekšskatījuma ir mainījušies/)).toBeTruthy()
    await waitFor(() => expect(api.previews()).toHaveLength(2))
    expect(api.changes()).toHaveLength(1) // never applied automatically
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.changes()).toHaveLength(1)
    expect(api.treeLoads()).toBe(2) // the tree behind the dialog was refreshed on the conflict

    await user.click(await confirmButton())
    await waitFor(() => expect(api.changes()).toHaveLength(2))
    expect(api.changes()[1].body?.expected_basis).toEqual(fresh) // the new preview's basis ...
    expect(api.changes()[1].body?.expected_version).toBe(6) // ... and the version that preview saw
  })

  it('after VERSION_CONFLICT refreshes the tree, keeps the dialog and the form, and waits', async () => {
    const fresh: BasisItem[] = BASIS.map((item) => (item.id === 's1' ? { ...item, version: 7 } : item))
    const api = mockApi({
      previews: [json(200, preview()), json(200, preview({ basis: fresh }))],
      changes: [error(409, 'VERSION_CONFLICT', { version: 7, status: 'active' })],
    })
    const user = await open()
    const li = row('W077')
    await user.click(within(li).getByRole('button', { name: 'Statuss' }))
    await user.selectOptions(within(li).getByLabelText('Jaunais statuss'), 'planned')
    await user.type(within(li).getByLabelText('Iemesls'), 'Sezonas beigas')
    await user.click(within(li).getByRole('button', { name: 'Mainīt statusu' }))
    await user.click(await confirmButton())

    const box = await dialog()
    expect(await within(box).findByText(/Kāds šo ierakstu jau ir mainījis/)).toBeTruthy()
    await waitFor(() => expect(api.treeLoads()).toBe(2)) // refreshed behind the dialog
    await waitFor(() => expect(api.previews()).toHaveLength(2)) // current consequences
    expect(screen.getByRole('dialog')).toBe(box) // still the same, open dialog
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.changes()).toHaveLength(1) // nothing applied automatically

    // The form behind the dialog keeps what the admin entered.
    expect(li.isConnected).toBe(true) // the same row, not re-created by the refresh
    expect((within(li).getByLabelText('Jaunais statuss') as HTMLSelectElement).value).toBe('planned')
    expect((within(li).getByLabelText('Iemesls') as HTMLInputElement).value).toBe('Sezonas beigas')

    await user.click(await confirmButton())
    await waitFor(() => expect(api.changes()).toHaveLength(2))
    expect(api.changes()[1].body).toMatchObject({ status: 'planned', reason: 'Sezonas beigas', expected_version: 7 })
    expect(api.changes()[1].body?.expected_basis).toEqual(fresh)
  })

  it('reports CATALOGUE_BUSY and retries only when the admin asks', async () => {
    const api = mockApi({ changes: [error(409, 'CATALOGUE_BUSY')] })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    await user.click(await confirmButton())
    expect(await within(await dialog()).findByText(/Katalogu šobrīd maina cits administrators/)).toBeTruthy()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.changes()).toHaveLength(1)
    expect(api.previews()).toHaveLength(1)

    await user.click(await confirmButton())
    await waitFor(() => expect(api.changes()).toHaveLength(2))
  })

  it('shows an invalid change from the preview and allows no confirmation', async () => {
    const api = mockApi({ previews: [error(409, 'INVALID_STATUS_TRANSITION')] })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const box = await dialog()
    expect(await within(box).findByRole('alert')).toBeTruthy()
    expect((within(box).getByRole('button', { name: 'Apstiprināt' }) as HTMLButtonElement).disabled).toBe(true)
    expect(api.changes()).toEqual([])
  })

  it('keeps the dialog and the entered data after a 422 from the change', async () => {
    mockApi({ changes: [error(422, 'REASON_REQUIRED')] })
    const user = await open()
    const li = row('W077')
    await user.click(within(li).getByRole('button', { name: 'Statuss' }))
    await user.selectOptions(within(li).getByLabelText('Jaunais statuss'), 'planned')
    await user.type(within(li).getByLabelText('Iemesls'), 'Sezona')
    await user.click(within(li).getByRole('button', { name: 'Mainīt statusu' }))
    await user.click(await confirmButton())
    expect(await within(await dialog()).findByText('Norādiet iemeslu.')).toBeTruthy()
    await user.click(within(await dialog()).getByRole('button', { name: 'Atcelt' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect((within(li).getByLabelText('Iemesls') as HTMLInputElement).value).toBe('Sezona')
    expect((within(li).getByLabelText('Jaunais statuss') as HTMLSelectElement).value).toBe('planned')
  })

  it('confirms only once, however often the button is pressed', async () => {
    let finish: (r: Response) => void = () => undefined
    const api = mockApi({ changes: [new Promise<Response>((resolve) => (finish = resolve))] })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const button = await confirmButton()
    await user.click(button)
    await user.click(button)
    await user.dblClick(button)
    expect(api.changes()).toHaveLength(1)
    expect(within(await dialog()).getByRole('button', { name: 'Saglabā…' })).toBeTruthy()
    await act(async () => finish(json(200, {})))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.changes()).toHaveLength(1)
  })
})

// --- what the dialog shows ------------------------------------------------------------------------------------------

describe('impact dialog content', () => {
  it('lists at most 100 masters losing eligibility, with the total', async () => {
    const items = Array.from({ length: 100 }, (_, n) => ({ master_id: `m${n}`, full_name: `Meistars ${String(n).padStart(3, '0')}` }))
    mockApi({
      previews: [json(200, preview({ masters: { by_specialisation_status: {}, by_competency_status: {}, losing_eligibility: { total: 105, items } } }))],
    })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const box = await dialog()
    const list = await within(box).findByRole('list', { name: /zaudēs atbilstību — saraksts/ })
    expect(within(list).getAllByRole('listitem')).toHaveLength(100)
    expect(within(box).getByText('Rādīti 100 no 105.')).toBeTruthy()
    expect(within(box).getByText(/Meistari, kuri zaudēs atbilstību/).textContent).toContain('105')
  })

  it('shows open requests as not yet available, never as 0', async () => {
    mockApi()
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const box = await dialog()
    const section = (await within(box).findByRole('heading', { name: 'Atvērtie pieteikumi' })).closest('section') as HTMLElement
    expect(section.textContent).toContain('Dati būs pieejami, kad tiks ieviesti klientu pieteikumi (5. posms).')
    expect(section.textContent).not.toMatch(/\b0\b/)
  })

  it('shows before/after, every reason, the orderability changes and the Riga snapshot time', async () => {
    mockApi({
      previews: [
        json(
          200,
          preview({
            services: [
              {
                service_id: 's1',
                w_id: 'W077',
                name: 'Izlietnes uzstādīšana',
                before: { orderable: true, eligible_masters: 2, reasons: [] },
                after: {
                  orderable: false,
                  eligible_masters: 0,
                  reasons: [
                    { code: 'SPECIALISATION_NOT_ACTIVE', details: { id: 'sp1', status: 'planned' } },
                    { code: 'NO_ELIGIBLE_MASTERS', details: {} },
                  ],
                },
              },
              {
                service_id: 's3',
                w_id: 'W080',
                name: 'Krāna maiņa',
                before: { orderable: false, eligible_masters: 0, reasons: [{ code: 'NO_ELIGIBLE_MASTERS', details: {} }] },
                after: { orderable: true, eligible_masters: 1, reasons: [] },
              },
            ],
            stops_being_orderable: ['s1'],
            becomes_orderable: ['s3'],
          }),
        ),
      ],
    })
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const box = await dialog()
    const after = await within(box).findByRole('list', { name: 'Pēc: Iemesli, kāpēc pakalpojums nav pasūtāms' })
    expect(within(after).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Specializācija nav aktīva (Plānots)',
      'Nav neviena meistara, kas atbilst visām prasībām',
    ])
    expect(within(within(box).getByRole('list', { name: 'Vairs nebūs pasūtāmi' })).getByText(/W077/)).toBeTruthy()
    expect(within(within(box).getByRole('list', { name: 'Kļūs pasūtāmi' })).getByText(/W080/)).toBeTruthy()
    expect(within(box).getByText(/Specializāciju statusi: apstiprināta 2, pieteikta 1/)).toBeTruthy()
    expect(within(box).getByText(/Kompetenču statusi: apstiprināta 2/)).toBeTruthy()
    expect(within(box).getByText(/momentuzņēmums 02\.11\.26\.? 12:00:00|momentuzņēmums .*12:00:00/)).toBeTruthy() // 10:00 UTC = 12:00 Riga
    expect(within(box).getByText(/Rīgas laiks/)).toBeTruthy()
  })
})

// --- keyboard and focus -------------------------------------------------------------------------------------------

describe('impact dialog keyboard use', () => {
  it('takes focus, keeps Tab inside, closes on Escape and returns focus', async () => {
    mockApi()
    const user = await open()
    await changeStatus(user, 'W077', 'inactive')
    const box = await dialog()
    expect(box.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(box)
    await within(box).findByRole('button', { name: 'Apstiprināt' })
    await waitFor(() => expect((within(box).getByRole('button', { name: 'Apstiprināt' }) as HTMLButtonElement).disabled).toBe(false))

    const confirm = within(box).getByRole('button', { name: 'Apstiprināt' })
    const cancel = within(box).getByRole('button', { name: 'Atcelt' })
    cancel.focus()
    await user.tab()
    expect(document.activeElement).toBe(confirm) // wraps around inside the dialog
    await user.tab({ shift: true })
    expect(document.activeElement).toBe(cancel)

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(within(row('W077')).getByRole('button', { name: 'Mainīt statusu' }))
  })
})
