import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AvailabilityReason, CatalogueTree, TreeService } from '../../../types/catalogue'
import { CataloguePage } from './CataloguePage'
import { TransferPage } from './TransferPage'

const entry = {
  description: null,
  status_reason: null,
  source: 'seed_cm_v1',
  source_ref: null,
  version: 1,
  updated_at: '2026-10-31T10:00:00Z',
}

function service(over: Partial<TreeService>): TreeService {
  const status = over.status ?? 'draft'
  return {
    ...entry,
    id: over.w_id ?? 's',
    name: 'X',
    sort_order: 0,
    specialisation_id: 'sp1',
    w_id: 'W071',
    status: 'draft',
    risk_level: 'normal',
    qualification_required: false,
    restrictions: null,
    review_note: null,
    qualification_ids: [],
    qualifications_ready: true,
    // As the backend reports a draft service: not orderable, nobody eligible.
    eligible_masters: 0,
    orderable: false,
    orderable_reasons: [{ code: 'SERVICE_NOT_ACTIVE', details: { id: over.w_id ?? 's', status } }],
    ...over,
  }
}

function tree(over: Partial<CatalogueTree> = {}): CatalogueTree {
  return {
    catalogue_role: 'issuer',
    can_create: true,
    qualifications: [],
    categories: [
      {
        ...entry,
        id: 'c1',
        name: 'Mazā santehnika un mājas meistaru darbi',
        status: 'active',
        sort_order: 0,
        specialisations: [
          {
            ...entry,
            id: 'sp1',
            category_id: 'c1',
            name: 'Izlietņu meistars',
            status: 'active',
            sort_order: 0,
            qualification_required: false,
            qualification_ids: [],
            services: [
              service({
                w_id: 'W077',
                name: 'Izlietnes uzstādīšana',
                review_note: 'Possible overlap',
              }),
              service({
                w_id: 'W103',
                name: 'Nelielas noplūdes novēršana',
                sort_order: 1,
                qualification_required: true,
                qualifications_ready: false,
              }),
              service({
                w_id: 'W079',
                name: 'Noraidīts pakalpojums',
                status: 'rejected',
                sort_order: 2,
              }),
            ],
          },
        ],
      },
    ],
    ...over,
  }
}

function mockFetch(body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage(page: React.ReactNode) {
  return render(<MemoryRouter>{page}</MemoryRouter>)
}

const CHANGE_STATUS = 'Mainīt statusu'

function impactResponse(basis: unknown[]) {
  return {
    entity: 'service',
    id: 'W077',
    change: { kind: 'status', status: 'inactive', reason: null },
    basis,
    services: [],
    stops_being_orderable: [],
    becomes_orderable: [],
    masters: { by_specialisation_status: {}, by_competency_status: {}, losing_eligibility: { total: 0, items: [] } },
    open_requests: null,
    notes: { open_requests: 'x', eligible_masters: 'x' },
    computed_at: '2026-11-02T10:00:00Z',
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('CataloguePage', () => {
  it('shows W-IDs, review flags and unconfigured qualifications, hiding rejected entries', async () => {
    mockFetch(tree())
    renderPage(<CataloguePage />)
    expect(await screen.findByText('W077')).toBeTruthy()
    expect(screen.getByText(/Possible overlap/)).toBeTruthy()
    expect(screen.getByText(/Kvalifikācijas nav konfigurētas/)).toBeTruthy()
    expect(screen.queryByText('W079')).toBeNull()
    await userEvent.click(screen.getByLabelText('Rādīt arhivētos un noraidītos'))
    expect(screen.getByText('W079')).toBeTruthy()
  })

  it('offers only allowed status transitions and requires a reason for reject', async () => {
    mockFetch(tree())
    renderPage(<CataloguePage />)
    const row = (await screen.findByText('W077')).closest('li') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Statuss' }))
    const select = within(row).getByLabelText('Jaunais statuss')
    const options = within(select)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(options).toEqual(['Aktīvs', 'Neaktīvs', 'Plānots', 'Noraidīts'])
    await userEvent.selectOptions(select, 'rejected')
    expect((within(row).getByLabelText('Iemesls') as HTMLInputElement).required).toBe(true)
  })

  it('sends the version of the entry it shows, through the impact preview, with a status change', async () => {
    const loaded = tree()
    loaded.categories[0].specialisations[0].services[0].version = 3
    const basis = [{ kind: 'service', id: 'W077', version: 3 }]
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/admin/catalogue/impact')) {
        return new Response(JSON.stringify(impactResponse(basis)), { status: 200 })
      }
      return new Response(JSON.stringify(init?.method === 'POST' ? {} : loaded), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage(<CataloguePage />)
    const row = (await screen.findByText('W077')).closest('li') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Statuss' }))
    await userEvent.selectOptions(within(row).getByLabelText('Jaunais statuss'), 'inactive')
    await userEvent.click(within(row).getByRole('button', { name: CHANGE_STATUS }))
    await userEvent.click(await screen.findByRole('button', { name: 'Apstiprināt' }))
    const [url, init] = fetchMock.mock.calls[2] as unknown as [string, RequestInit]
    expect(url).toContain('/admin/catalogue/services/W077/status')
    expect(JSON.parse(String(init.body))).toEqual({
      status: 'inactive',
      reason: null,
      expected_version: 3,
      expected_basis: basis,
    })
  })

  it('explains a version conflict and reloads the catalogue', async () => {
    const conflict = { error: { code: 'VERSION_CONFLICT', message: 'x', details: { version: 2 } } }
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'PATCH'
        ? new Response(JSON.stringify(conflict), { status: 409 })
        : new Response(JSON.stringify(tree()), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPage(<CataloguePage />)
    const row = (await screen.findByText('W077')).closest('li') as HTMLElement
    // A name change does not affect availability: it is saved directly, with the version.
    await userEvent.click(within(row).getByRole('button', { name: 'Labot' }))
    const name = within(row).getByLabelText('Nosaukums')
    await userEvent.clear(name)
    await userEvent.type(name, 'Jauns nosaukums')
    await userEvent.click(within(row).getByRole('button', { name: 'Saglabāt' }))
    expect(await screen.findByText(/Kāds šo ierakstu jau ir mainījis/)).toBeTruthy()
    const treeLoads = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/admin/catalogue/tree'))
    expect(treeLoads).toHaveLength(2) // loaded, then reloaded after the conflict
  })

  it('hides creation on staging and explains why', async () => {
    mockFetch(tree({ catalogue_role: 'receiver', can_create: false }))
    renderPage(<CataloguePage />)
    expect(await screen.findByText(/jaunus kataloga ierakstus veido tikai produkcijā/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Pievienot kategoriju' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pievienot pakalpojumu' })).toBeNull()
  })
})

describe('TransferPage', () => {
  it('shows import only on the receiving environment', async () => {
    mockFetch(tree())
    const { unmount } = renderPage(<TransferPage />)
    expect(await screen.findByRole('button', { name: 'Lejupielādēt paketi' })).toBeTruthy()
    expect(screen.queryByLabelText('Kataloga pakete (JSON)')).toBeNull()
    unmount()

    mockFetch(tree({ catalogue_role: 'receiver', can_create: false }))
    renderPage(<TransferPage />)
    expect(await screen.findByLabelText('Kataloga pakete (JSON)')).toBeTruthy()
  })
})

describe('CataloguePage availability (step 4.6.1)', () => {
  function withService(over: Partial<TreeService>, parents: { category?: string; spec?: string } = {}) {
    const loaded = tree()
    const category = loaded.categories[0]
    if (parents.category) category.status = parents.category as typeof category.status
    const spec = category.specialisations[0]
    if (parents.spec) spec.status = parents.spec as typeof spec.status
    spec.services = [service({ w_id: 'W200', name: 'Pārbaudāmais pakalpojums', status: 'active', ...over })]
    return loaded
  }

  async function serviceRow(): Promise<HTMLElement> {
    return (await screen.findByText('W200')).closest('li') as HTMLElement
  }

  function reason(code: string, details: Record<string, unknown> = {}): AvailabilityReason {
    return { code, details }
  }

  it('shows an orderable service with its number of eligible masters', async () => {
    mockFetch(withService({ orderable: true, eligible_masters: 3, orderable_reasons: [] }))
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    expect(within(row).getByText('Pasūtāms')).toBeTruthy()
    expect(within(row).getByText(/Atbilstošie meistari:\s*3/)).toBeTruthy()
    expect(within(row).queryByRole('list', { name: 'Iemesli, kāpēc pakalpojums nav pasūtāms' })).toBeNull()
  })

  it('shows zero eligible masters', async () => {
    mockFetch(withService({ orderable: false, eligible_masters: 0, orderable_reasons: [reason('NO_ELIGIBLE_MASTERS')] }))
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    expect(within(row).getByText('Nav pasūtāms')).toBeTruthy()
    expect(within(row).getByText(/Atbilstošie meistari:\s*0/)).toBeTruthy()
  })

  it.each([
    [reason('SERVICE_NOT_ACTIVE', { id: 'W200', status: 'hold' }), 'Pakalpojums nav aktīvs (HOLD)'],
    [reason('SPECIALISATION_NOT_ACTIVE', { id: 'sp1', status: 'planned' }), 'Specializācija nav aktīva (Plānots)'],
    [reason('CATEGORY_NOT_ACTIVE', { id: 'c1', status: 'inactive' }), 'Kategorija nav aktīva (Neaktīvs)'],
    [
      reason('QUALIFICATION_NOT_CONFIGURED'),
      'Regulētam pakalpojumam nav konfigurētas aktīvas kvalifikāciju prasības',
    ],
    [reason('NO_ELIGIBLE_MASTERS'), 'Nav neviena meistara, kas atbilst visām prasībām'],
  ])('explains %j in Latvian', async (why, text) => {
    mockFetch(withService({ orderable: false, eligible_masters: 1, orderable_reasons: [why] }))
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    const list = within(row).getByRole('list', { name: 'Iemesli, kāpēc pakalpojums nav pasūtāms' })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([text])
  })

  it('lists every reason, in the order the backend gives them', async () => {
    mockFetch(
      withService({
        orderable: false,
        eligible_masters: 0,
        orderable_reasons: [
          reason('SERVICE_NOT_ACTIVE', { id: 'W200', status: 'planned' }),
          reason('SPECIALISATION_NOT_ACTIVE', { id: 'sp1', status: 'inactive' }),
          reason('QUALIFICATION_NOT_CONFIGURED'),
          reason('NO_ELIGIBLE_MASTERS'),
        ],
      }),
    )
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    const items = within(within(row).getByRole('list', { name: 'Iemesli, kāpēc pakalpojums nav pasūtāms' }))
      .getAllByRole('listitem')
      .map((li) => li.textContent)
    expect(items).toEqual([
      'Pakalpojums nav aktīvs (Plānots)',
      'Specializācija nav aktīva (Neaktīvs)',
      'Regulētam pakalpojumam nav konfigurētas aktīvas kvalifikāciju prasības',
      'Nav neviena meistara, kas atbilst visām prasībām',
    ])
  })

  it('keeps a service under inactive parents visible, with the backend reason', async () => {
    mockFetch(
      withService(
        {
          orderable: false,
          eligible_masters: 2,
          orderable_reasons: [
            reason('SPECIALISATION_NOT_ACTIVE', { id: 'sp1', status: 'planned' }),
            reason('CATEGORY_NOT_ACTIVE', { id: 'c1', status: 'inactive' }),
          ],
        },
        { category: 'inactive', spec: 'planned' },
      ),
    )
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    expect(within(row).getByText('Pārbaudāmais pakalpojums')).toBeTruthy()
    expect(within(row).getByText(/Atbilstošie meistari:\s*2/)).toBeTruthy()
    expect(within(row).getByText('Kategorija nav aktīva (Neaktīvs)')).toBeTruthy()
  })

  it('shows an unknown reason code as is rather than hiding it', async () => {
    mockFetch(withService({ orderable: false, orderable_reasons: [reason('SOMETHING_NEW')] }))
    renderPage(<CataloguePage />)
    const row = await serviceRow()
    expect(within(row).getByText('SOMETHING_NEW')).toBeTruthy()
  })
})
