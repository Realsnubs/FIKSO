import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BasisItem, ImpactRequest, ImpactResponse } from '../types/catalogue'
import { ApiError } from './client'
import { catalogueApi } from './endpoints'

const BASIS: BasisItem[] = [
  { kind: 'category', id: 'c1', version: 2 },
  { kind: 'specialisation', id: 'sp1', version: 5 },
  { kind: 'service', id: 's1', version: 3 },
  { kind: 'qualification', id: 'q1', version: 1 },
]

const RESPONSE: ImpactResponse = {
  entity: 'service',
  id: 's1',
  change: { kind: 'status', status: 'inactive', reason: null },
  basis: BASIS,
  services: [
    {
      service_id: 's1',
      w_id: 'W071',
      name: 'Tualetes poda uzstādīšana',
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
    by_specialisation_status: { approved: 2 },
    by_competency_status: { verified: 2 },
    losing_eligibility: { total: 0, items: [] },
  },
  open_requests: null,
  notes: { open_requests: 'Not available yet', eligible_masters: 'A snapshot at computed_at' },
  computed_at: '2026-11-02T10:00:00Z',
}

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sent(fetchMock: ReturnType<typeof respond>): { url: string; method: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  return { url, method: String(init.method), body: JSON.parse(String(init.body)) }
}

afterEach(() => vi.unstubAllGlobals())

describe('catalogueApi.previewImpact', () => {
  it('posts the request to the impact route and returns the typed preview', async () => {
    const fetchMock = respond(200, RESPONSE)
    const request: ImpactRequest = { entity: 'service', id: 's1', change: { kind: 'status', status: 'inactive' } }
    await expect(catalogueApi.previewImpact(request)).resolves.toEqual(RESPONSE)
    expect(sent(fetchMock)).toEqual({ url: '/api/v1/admin/catalogue/impact', method: 'POST', body: request })
  })

  it.each<ImpactRequest>([
    { entity: 'category', id: 'c1', change: { kind: 'status', status: 'inactive' } },
    { entity: 'specialisation', id: 'sp1', change: { kind: 'status', status: 'archived', reason: 'Slēgts' } },
    { entity: 'specialisation', id: 'sp1', change: { kind: 'move', target_id: 'c2' } },
    { entity: 'specialisation', id: 'sp1', change: { kind: 'qualification_required', value: true } },
    { entity: 'specialisation', id: 'sp1', change: { kind: 'requirements', qualification_ids: ['q1'] } },
    { entity: 'service', id: 's1', change: { kind: 'move', target_id: 'sp2' } },
    { entity: 'service', id: 's1', change: { kind: 'qualification_required', value: false } },
    { entity: 'service', id: 's1', change: { kind: 'requirements', qualification_ids: [] } },
    { entity: 'service', id: 's1', change: { kind: 'activate_hold', reason: 'Pārbaudīts' } },
  ])('sends %j unchanged', async (request) => {
    const fetchMock = respond(200, RESPONSE)
    await catalogueApi.previewImpact(request)
    expect(sent(fetchMock).body).toEqual(request)
  })

  it.each([
    ['IMPACT_CHANGE_NOT_SUPPORTED', 422],
    ['CATALOGUE_BUSY', 409],
    ['INVALID_STATUS_TRANSITION', 409],
  ])('reports %s through the usual ApiError', async (code, status) => {
    respond(status, { error: { code, message: 'x', details: {} } })
    const error = await catalogueApi
      .previewImpact({ entity: 'service', id: 's1', change: { kind: 'status', status: 'draft' } })
      .catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status, code })
  })

  it('only allows the combinations the backend previews (checked by tsc)', () => {
    const allowed: ImpactRequest[] = [
      // @ts-expect-error a category is previewed only for its status
      { entity: 'category', id: 'c1', change: { kind: 'move', target_id: 'c2' } },
      // @ts-expect-error HOLD activation exists only for services
      { entity: 'specialisation', id: 'sp1', change: { kind: 'activate_hold', reason: 'Pārbaudīts' } },
    ]
    expect(allowed).toHaveLength(2)
  })
})

describe('expected_basis on the change routes', () => {
  const calls: [string, () => Promise<unknown>, string, string, Record<string, unknown>][] = [
    [
      'setStatus (service)',
      () => catalogueApi.setStatus('services', 's1', 'inactive', undefined, 3, BASIS),
      'POST',
      '/api/v1/admin/catalogue/services/s1/status',
      { status: 'inactive', reason: null, expected_version: 3 },
    ],
    [
      'setStatus (specialisation)',
      () => catalogueApi.setStatus('specialisations', 'sp1', 'archived', 'Slēgts', 5, BASIS),
      'POST',
      '/api/v1/admin/catalogue/specialisations/sp1/status',
      { status: 'archived', reason: 'Slēgts', expected_version: 5 },
    ],
    [
      'setStatus (category)',
      () => catalogueApi.setStatus('categories', 'c1', 'inactive', undefined, 2, BASIS),
      'POST',
      '/api/v1/admin/catalogue/categories/c1/status',
      { status: 'inactive', reason: null, expected_version: 2 },
    ],
    [
      'update (service move)',
      () => catalogueApi.update('services', 's1', { specialisation_id: 'sp2' }, 3, BASIS),
      'PATCH',
      '/api/v1/admin/catalogue/services/s1',
      { specialisation_id: 'sp2', expected_version: 3 },
    ],
    [
      'update (specialisation flag)',
      () => catalogueApi.update('specialisations', 'sp1', { qualification_required: true }, 5, BASIS),
      'PATCH',
      '/api/v1/admin/catalogue/specialisations/sp1',
      { qualification_required: true, expected_version: 5 },
    ],
    [
      'setRequirements',
      () => catalogueApi.setRequirements('services', 's1', ['q1'], 3, BASIS),
      'PUT',
      '/api/v1/admin/catalogue/services/s1/qualifications',
      { qualification_ids: ['q1'], expected_version: 3 },
    ],
    [
      'activateHold',
      () => catalogueApi.activateHold('s1', 'Pārbaudīts', 3, BASIS),
      'POST',
      '/api/v1/admin/catalogue/services/s1/activate-hold',
      { confirm: true, reason: 'Pārbaudīts', expected_version: 3 },
    ],
  ]

  it.each(calls)('%s sends the basis as expected_basis', async (_name, call, method, url, body) => {
    const fetchMock = respond(200, {})
    await call()
    expect(sent(fetchMock)).toEqual({ url, method, body: { ...body, expected_basis: BASIS } })
  })

  it.each([
    ['setStatus', () => catalogueApi.setStatus('services', 's1', 'inactive', undefined, 3), {
      status: 'inactive',
      reason: null,
      expected_version: 3,
    }],
    ['update', () => catalogueApi.update('services', 's1', { name: 'Jauns' }, 3), {
      name: 'Jauns',
      expected_version: 3,
    }],
    ['update (qualification type)', () => catalogueApi.update('qualifications', 'q1', { name: 'Q' }, null), {
      name: 'Q',
    }],
    ['setRequirements', () => catalogueApi.setRequirements('specialisations', 'sp1', [], 5), {
      qualification_ids: [],
      expected_version: 5,
    }],
    ['activateHold', () => catalogueApi.activateHold('s1', 'Pārbaudīts', 3), {
      confirm: true,
      reason: 'Pārbaudīts',
      expected_version: 3,
    }],
  ] as [string, () => Promise<unknown>, Record<string, unknown>][])(
    '%s without a basis sends no expected_basis field',
    async (_name, call, body) => {
      const fetchMock = respond(200, {})
      await call()
      const request = sent(fetchMock).body as Record<string, unknown>
      expect(request).toEqual(body)
      expect('expected_basis' in request).toBe(false)
    },
  )

  it('surfaces IMPACT_PREVIEW_OUTDATED with its details', async () => {
    const details = { changed: [{ kind: 'service', id: 's1', expected: 3, current: 4 }], added: [], removed: [] }
    respond(409, { error: { code: 'IMPACT_PREVIEW_OUTDATED', message: 'x', details } })
    const error = await catalogueApi.setStatus('services', 's1', 'inactive', undefined, 3, BASIS).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'IMPACT_PREVIEW_OUTDATED', details })
  })

  it('refuses a basis where the backend has none (checked by tsc)', () => {
    const forbidden = [
      // @ts-expect-error a category PATCH (name, description) takes no basis
      () => catalogueApi.update('categories', 'c1', { name: 'X' }, 2, BASIS),
      // @ts-expect-error a qualification-type status change takes no basis
      () => catalogueApi.setStatus('qualifications', 'q1', 'archived', 'Vecs', 1, BASIS),
    ]
    expect(forbidden).toHaveLength(2)
  })
})
