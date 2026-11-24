import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../../App'
import { adminMastersApi } from '../../../api/endpoints'
import { AuthContext, type AuthState } from '../../../auth/context'
import type { User } from '../../../types/api'
import type { AdminCompetency, AdminMaster, BulkPreview, DecisionReason } from '../../../types/masters'

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

const auth: AuthState = {
  user: admin,
  ready: true,
  login: async () => {
    throw new Error('not used')
  },
  register: async () => {
    throw new Error('not used')
  },
  logout: async () => {},
  startGuest: async () => {
    throw new Error('not used')
  },
  loginWithCode: async () => {
    throw new Error('not used')
  },
  setPassword: async () => {
    throw new Error('not used')
  },
}

function competency(serviceId: string, wId: string, name: string, over: Partial<AdminCompetency> = {}): AdminCompetency {
  return {
    service_id: serviceId,
    w_id: wId,
    name,
    specialisation_id: 'sp1',
    status: 'declared',
    declared_at: '2026-10-02T08:05:00Z',
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    version: 1,
    eligible: false,
    reasons: [],
    ...over,
  }
}

const REGULATED: DecisionReason = {
  code: 'REGULATED_SERVICE',
  details: { service_qualification_required: true, specialisation_qualification_required: false, required_qualifications: 1 },
}

/**
 * A tiny backend: the competencies of master m1 plus which services are regulated (or blocked otherwise).
 * Preview answers from it like the real one (request order, current versions, applicable = all verifiable);
 * apply re-checks every item and verifies all or none.
 */
function backend(competencies: AdminCompetency[], blocked: Record<string, DecisionReason[]> = {}) {
  const state = {
    competencies: competencies.map((c) => ({ ...c })),
    blocked: { ...blocked },
  }
  const card = (): AdminMaster => ({
    id: 'm1',
    user_id: 'u1',
    full_name: 'Jānis Bērziņš',
    email: 'janis@example.lv',
    phone: null,
    user_status: 'active',
    blocked_reason: null,
    approval_status: 'approved',
    decided_by: 'a1',
    decided_at: '2026-10-03T08:00:00Z',
    decision_reason: null,
    version: 2,
    registered_at: '2026-10-01T09:00:00Z',
    today: '2026-11-02',
    specialisations: [],
    competencies: state.competencies.map((c) => ({ ...c })),
    qualifications: [],
    qualification_types: [],
  })
  const reasonsOf = (id: string, version?: number): DecisionReason[] => {
    const row = state.competencies.find((c) => c.service_id === id)
    if (!row) return [{ code: 'COMPETENCY_NOT_FOUND', details: {} }]
    const reasons: DecisionReason[] = []
    if (version !== undefined && version !== row.version) {
      reasons.push({ code: 'VERSION_CONFLICT', details: { status: row.status, version: row.version } })
    } else if (row.status !== 'declared') {
      reasons.push({ code: 'INVALID_TRANSITION', details: { status: row.status } })
    }
    return [...reasons, ...(state.blocked[id] ?? [])]
  }
  const preview = (ids: string[]): BulkPreview => {
    const items = ids.map((id) => {
      const row = state.competencies.find((c) => c.service_id === id)
      const reasons = reasonsOf(id)
      return {
        service_id: id,
        w_id: row?.w_id ?? null,
        name: row?.name ?? null,
        status: row?.status ?? null,
        expected_version: row?.version ?? null,
        verifiable: reasons.length === 0,
        reasons,
      }
    })
    return { items, applicable: items.every((i) => i.verifiable) }
  }
  const apply = (items: { service_id: string; expected_version: number }[]) => {
    const failures = items
      .map((i) => ({ service_id: i.service_id, reasons: reasonsOf(i.service_id, i.expected_version) }))
      .filter((f) => f.reasons.length > 0)
    if (failures.length > 0) return { status: 409, body: { error: { code: 'BULK_VERIFY_REJECTED', message: 'x', details: { items: failures } } } }
    for (const i of items) {
      const row = state.competencies.find((c) => c.service_id === i.service_id)!
      row.status = 'verified'
      row.version += 1
    }
    return { status: 200, body: card() }
  }
  return { state, card, preview, apply }
}

interface Call {
  method: string
  path: string
  body: unknown
}

const BASE = '/api/v1/admin/masters/m1'
const PREVIEW = `${BASE}/competencies/bulk-verify/preview`
const APPLY = `${BASE}/competencies/bulk-verify`

type Override = (call: Call) => Response | Promise<Response> | undefined

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Serves the fake backend; `override` may answer a call first (errors, delays). */
function serve(api: ReturnType<typeof backend>, override?: Override) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const call: Call = {
        method: init?.method ?? 'GET',
        path: new URL(input, 'http://localhost').pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const custom = override?.(call)
      if (custom) return custom
      if (call.method === 'GET' && call.path === BASE) return json(api.card())
      if (call.path === PREVIEW) return json(api.preview((call.body as { service_ids: string[] }).service_ids))
      if (call.path === APPLY) {
        const result = api.apply((call.body as { items: { service_id: string; expected_version: number }[] }).items)
        return json(result.body, result.status)
      }
      const single = /\/competencies\/([^/]+)\/verify$/.exec(call.path)
      if (single) {
        const row = api.state.competencies.find((c) => c.service_id === single[1])!
        row.status = 'verified'
        row.version += 1
        return json(api.card())
      }
      return json({ error: { code: 'NOT_FOUND', message: 'x' } }, 404)
    }),
  )
  return {
    calls,
    previews: () => calls.filter((c) => c.path === PREVIEW).map((c) => (c.body as { service_ids: string[] }).service_ids),
    applies: () => calls.filter((c) => c.path === APPLY).map((c) => c.body),
    cardLoads: () => calls.filter((c) => c.method === 'GET' && c.path === BASE).length,
  }
}

function standard() {
  return backend(
    [
      competency('s1', 'W071', 'Tualetes poda uzstādīšana'),
      competency('s2', 'W072', 'Izlietnes uzstādīšana', { version: 2 }),
      competency('s3', 'W073', 'Gāzes plīts pieslēgšana'),
      competency('s4', 'W090', 'Rozetes nomaiņa', { status: 'verified', version: 4 }),
    ],
    { s3: [REGULATED] },
  )
}

function renderCard() {
  return render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={['/admin/masters/m1']}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

async function openSelection() {
  await screen.findByRole('heading', { level: 1, name: 'Jānis Bērziņš' })
  await userEvent.click(screen.getByRole('button', { name: 'Atlasīt kompetences masveida apstiprināšanai' }))
  return screen.findByRole('group', { name: 'Pieteiktās kompetences' })
}

const box = (name: RegExp) => screen.getByRole('checkbox', { name }) as HTMLInputElement

async function openPreview(count: number) {
  await userEvent.click(screen.getByRole('button', { name: `Priekšskatīt (${count})` }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Masveida apstiprināšanas priekšskatījums' })
  await within(dialog).findByText(`Atlasītas kompetences: ${count}`)
  return dialog
}

function competencyRow(wId: string) {
  const list = screen.getByRole('list', { name: 'Kompetences' })
  return within(list)
    .getAllByRole('listitem')
    .find((li) => li.querySelector('.user-head')?.textContent?.includes(wId)) as HTMLElement
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('bulk verification: selection', () => {
  it('is not offered when no competency waits for verification', async () => {
    serve(backend([competency('s4', 'W090', 'Rozetes nomaiņa', { status: 'verified', version: 4 })]))
    renderCard()
    await screen.findByRole('heading', { level: 1, name: 'Jānis Bērziņš' })
    expect(screen.queryByRole('button', { name: 'Atlasīt kompetences masveida apstiprināšanai' })).toBeNull()
  })

  it('asks the backend preview which declared competencies are available, writing nothing', async () => {
    const api = standard()
    const io = serve(api)
    renderCard()
    await openSelection()
    expect(io.previews()).toEqual([['s1', 's2', 's3']]) // declared only; the verified W090 is not a candidate
    expect(io.applies()).toEqual([])
    expect(screen.queryByRole('checkbox', { name: /W090/ })).toBeNull()
    expect(box(/W071/).disabled).toBe(false)
    expect(box(/W072/).disabled).toBe(false)
    expect(api.state.competencies.map((c) => c.status)).toEqual(['declared', 'declared', 'declared', 'verified'])
  })

  it('a regulated competency cannot be selected and shows the backend reason', async () => {
    serve(standard())
    renderCard()
    await openSelection()
    const regulated = box(/W073/)
    expect(regulated.disabled).toBe(true)
    await userEvent.click(regulated)
    expect(regulated.checked).toBe(false)
    const reasons = screen.getByRole('list', { name: 'Masveidā apstiprināt nevar: W073' })
    expect(reasons.textContent).toBe('Regulētu pakalpojumu apstiprina atsevišķi')
    await userEvent.click(screen.getByRole('button', { name: 'Atlasīt visas pieejamās' }))
    expect(regulated.checked).toBe(false)
    expect(screen.getByRole('button', { name: 'Priekšskatīt (2)' })).toBeTruthy()
  })

  it('selects one and several competencies, and clears the selection', async () => {
    serve(standard())
    renderCard()
    await openSelection()
    const preview = () => screen.getByRole('button', { name: /^Priekšskatīt/ }) as HTMLButtonElement
    expect(preview().textContent).toBe('Priekšskatīt (0)')
    expect(preview().disabled).toBe(true) // nothing to preview, nothing to apply
    await userEvent.click(box(/W072/))
    expect(preview().textContent).toBe('Priekšskatīt (1)')
    await userEvent.click(box(/W071/))
    expect(preview().textContent).toBe('Priekšskatīt (2)')
    await userEvent.click(box(/W072/))
    expect(preview().textContent).toBe('Priekšskatīt (1)')
    await userEvent.click(screen.getByRole('button', { name: 'Notīrīt atlasi' }))
    expect(preview().disabled).toBe(true)
  })

  it('shows when nothing can be bulk-verified', async () => {
    serve(backend([competency('s3', 'W073', 'Gāzes plīts pieslēgšana')], { s3: [REGULATED] }))
    renderCard()
    await openSelection()
    expect(screen.getByText('Nevienu pieteikto kompetenci nevar apstiprināt masveidā.')).toBeTruthy()
  })

  it('checks more than 50 candidates in chunks and selects at most 50', async () => {
    const many = Array.from({ length: 51 }, (_, i) =>
      competency(`s${i + 1}`, `W${String(200 + i)}`, `Pakalpojums ${i + 1}`),
    )
    const io = serve(backend(many))
    renderCard()
    await openSelection()
    expect(io.previews().map((ids) => ids.length)).toEqual([50, 1])
    await userEvent.click(screen.getByRole('button', { name: 'Atlasīt visas pieejamās' }))
    expect(screen.getByRole('button', { name: 'Priekšskatīt (50)' })).toBeTruthy()
    expect(box(/W250/).disabled).toBe(true)
    expect(screen.getByText('Vienā reizē var atlasīt ne vairāk kā 50 kompetences.')).toBeTruthy()
  })

  it('reports an availability error in Latvian and retries', async () => {
    let fail = true
    serve(standard(), (call) =>
      call.path === PREVIEW && fail ? new Response('down', { status: 502 }) : undefined,
    )
    renderCard()
    await screen.findByRole('heading', { level: 1, name: 'Jānis Bērziņš' })
    await userEvent.click(screen.getByRole('button', { name: 'Atlasīt kompetences masveida apstiprināšanai' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Radās kļūda. Mēģiniet vēlreiz.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Mēģināt vēlreiz' }))
    expect(await screen.findByRole('group', { name: 'Pieteiktās kompetences' })).toBeTruthy()
  })

  it('marks the availability out of date when the card changes, until checked again', async () => {
    const io = serve(standard())
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    // A single verification of W072 changes the card behind the selection.
    await userEvent.click(screen.getByRole('button', { name: 'Apstiprināt: W072 Izlietnes uzstādīšana' }))
    expect(await screen.findByText(/Kompetenču dati kopš pārbaudes ir mainījušies/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Priekšskatīt (1)' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('group', { name: 'Pieteiktās kompetences' })).toHaveProperty('disabled', true)
    await userEvent.click(screen.getByRole('button', { name: 'Pārbaudīt vēlreiz' }))
    await waitFor(() => expect(io.previews().at(-1)).toEqual(['s1', 's3']))
    expect(screen.getByRole('button', { name: 'Priekšskatīt (1)' })).toHaveProperty('disabled', false)
  })
})

describe('bulk verification: preview and apply', () => {
  it('previews exactly the selection without changing anything; cancelling applies nothing', async () => {
    const api = standard()
    const io = serve(api)
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    expect(io.previews().at(-1)).toEqual(['s1'])
    expect(within(dialog).getByText(/Ja kaut viena vairs neatbilst prasībām, netiks apstiprināta neviena/)).toBeTruthy()
    const list = within(dialog).getByRole('list', { name: 'Atlasītās kompetences' })
    expect(list.textContent).toContain('W071 Tualetes poda uzstādīšana')
    expect(list.textContent).toContain('Var apstiprināt')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Atcelt' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(io.applies()).toEqual([])
    expect(api.state.competencies[0].status).toBe('declared')
  })

  it('Escape closes the preview without applying', async () => {
    const io = serve(standard())
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    await openPreview(1)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(io.applies()).toEqual([])
  })

  it('applies one competency with confirm=true and the version from the preview, then shows the new card', async () => {
    const io = serve(standard())
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' }))
    expect(await screen.findByText('Apstiprinātas kompetences: 1.')).toBeTruthy()
    expect(io.applies()).toEqual([{ items: [{ service_id: 's1', expected_version: 1 }], confirm: true }])
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(within(competencyRow('W071')).getByText('apstiprināta')).toBeTruthy()
    expect(within(competencyRow('W072')).getByText('pieteikta')).toBeTruthy()
    expect(io.cardLoads()).toBe(1) // the apply answer is the committed card
  })

  it('applies the full selection in card order with each version', async () => {
    const io = serve(standard())
    renderCard()
    await openSelection()
    await userEvent.click(box(/W072/))
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(2)
    expect(io.previews().at(-1)).toEqual(['s1', 's2'])
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (2)' }))
    expect(await screen.findByText('Apstiprinātas kompetences: 2.')).toBeTruthy()
    expect(io.applies()).toEqual([
      {
        items: [
          { service_id: 's1', expected_version: 1 },
          { service_id: 's2', expected_version: 2 },
        ],
        confirm: true,
      },
    ])
    expect(within(competencyRow('W071')).getByText('apstiprināta')).toBeTruthy()
    expect(within(competencyRow('W072')).getByText('apstiprināta')).toBeTruthy()
    // Nothing left to bulk-verify but the regulated one; the selection is closed.
    expect(screen.queryByRole('group', { name: 'Pieteiktās kompetences' })).toBeNull()
  })

  it('a selection the backend no longer accepts cannot be confirmed', async () => {
    const api = standard()
    const io = serve(api)
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    await userEvent.click(box(/W072/))
    // W072 becomes blocked after the availability check, before the preview.
    api.state.blocked.s2 = [{ code: 'QUALIFICATION_NOT_CONFIGURED', details: { service_id: 's2' } }]
    const dialog = await openPreview(2)
    expect(within(dialog).getByText(/Šo atlasi apstiprināt nevar/)).toBeTruthy()
    expect(within(dialog).getByRole('list', { name: 'Masveidā apstiprināt nevar: W072 Izlietnes uzstādīšana' }).textContent).toBe(
      'Regulētam pakalpojumam nav konfigurētas aktīvas kvalifikāciju prasības',
    )
    const confirm = within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (2)' })
    expect(confirm).toHaveProperty('disabled', true)
    await userEvent.click(confirm)
    expect(io.applies()).toEqual([])
  })

  it('all or nothing: a refused apply verifies nothing, reloads the card and requires a new confirmation', async () => {
    const api = standard()
    const io = serve(api)
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    await userEvent.click(box(/W072/))
    const dialog = await openPreview(2)
    // Another admin changes W072 after the preview (a new version, still declared).
    api.state.competencies[1].version = 3
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (2)' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert.textContent).toContain('Neviena kompetence netika apstiprināta')
    expect(within(alert).getByRole('list', { name: 'Kāpēc apstiprināšana tika atteikta' }).textContent).toBe(
      'W072 Izlietnes uzstādīšana: Kompetence kopš priekšskatījuma ir mainīta',
    )
    await waitFor(() => expect(io.cardLoads()).toBe(2))
    await within(dialog).findByText('Atlasītas kompetences: 2')
    expect(io.previews().at(-1)).toEqual(['s1', 's2'])
    // Nothing was verified, on the server or on screen.
    expect(api.state.competencies.slice(0, 2).map((c) => c.status)).toEqual(['declared', 'declared'])
    expect(within(competencyRow('W071')).getByText('pieteikta')).toBeTruthy()
    expect(io.applies()).toHaveLength(1) // no automatic retry
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (2)' }))
    expect(await screen.findByText('Apstiprinātas kompetences: 2.')).toBeTruthy()
    expect(io.applies()[1]).toEqual({
      items: [
        { service_id: 's1', expected_version: 1 },
        { service_id: 's2', expected_version: 3 },
      ],
      confirm: true,
    })
  })

  it('after a refusal whose cause remains, the new preview cannot be confirmed', async () => {
    const api = standard()
    const io = serve(api)
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    api.state.competencies[0].status = 'rejected' // decided by someone else meanwhile
    api.state.competencies[0].version = 2
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' }))
    expect(await within(dialog).findByText(/Šo atlasi apstiprināt nevar/)).toBeTruthy()
    expect(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' })).toHaveProperty('disabled', true)
    expect(io.applies()).toHaveLength(1)
  })

  it.each([
    ['DECISION_FORBIDDEN', 403, 'Jūs nevarat pieņemt lēmumus par šo meistaru.'],
    ['BULK_VERIFY_INVALID', 422, 'Atlasiet no 1 līdz 50 dažādām kompetencēm.'],
    ['MASTER_NOT_FOUND', 404, 'Meistars nav atrasts.'],
    ['SOMETHING_NEW', 500, 'Radās kļūda. Mēģiniet vēlreiz.'],
  ])('reports %s in Latvian and keeps the preview', async (code, status, text) => {
    const io = serve(standard(), (call) =>
      call.path === APPLY ? json({ error: { code, message: 'x', details: {} } }, status) : undefined,
    )
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' }))
    expect((await within(dialog).findByRole('alert')).textContent).toBe(text)
    expect(within(dialog).getByText('Atlasītas kompetences: 1')).toBeTruthy()
    expect(io.cardLoads()).toBe(1)
    expect(within(competencyRow('W071')).getByText('pieteikta')).toBeTruthy()
  })

  it('a preview error is shown and nothing can be confirmed', async () => {
    let calls = 0
    const io = serve(standard(), (call) =>
      call.path === PREVIEW && ++calls === 2 ? json({ error: { code: 'MASTER_NOT_FOUND', message: 'x' } }, 404) : undefined,
    )
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    await userEvent.click(screen.getByRole('button', { name: 'Priekšskatīt (1)' }))
    const dialog = await screen.findByRole('alertdialog')
    expect((await within(dialog).findByRole('alert')).textContent).toBe('Meistars nav atrasts.')
    expect(within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' })).toHaveProperty('disabled', true)
    expect(io.applies()).toEqual([])
  })

  it('a double click applies once and locks the dialog meanwhile', async () => {
    let release: (r: Response) => void = () => {}
    const api = standard()
    const io = serve(api, (call) => (call.path === APPLY ? new Promise<Response>((r) => (release = r)) : undefined))
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    const confirm = within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' })
    await userEvent.dblClick(confirm)
    expect(io.applies()).toHaveLength(1)
    expect(confirm.textContent).toBe('Saglabā…')
    expect(confirm).toHaveProperty('disabled', true)
    expect(within(dialog).getByRole('button', { name: 'Atcelt' })).toHaveProperty('disabled', true)
    const result = api.apply([{ service_id: 's1', expected_version: 1 }])
    await act(async () => release(json(result.body, result.status)))
    expect(await screen.findByText('Apstiprinātas kompetences: 1.')).toBeTruthy()
    expect(io.applies()).toHaveLength(1)
  })

  it('two confirmations in the same tick still apply once', async () => {
    let release: (r: Response) => void = () => {}
    const api = standard()
    const io = serve(api, (call) => (call.path === APPLY ? new Promise<Response>((r) => (release = r)) : undefined))
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    const dialog = await openPreview(1)
    const confirm = within(dialog).getByRole('button', { name: 'Apstiprināt atlasītās (1)' })
    act(() => {
      confirm.click()
      confirm.click()
    })
    await waitFor(() => expect(io.applies()).toHaveLength(1))
    const result = api.apply([{ service_id: 's1', expected_version: 1 }])
    await act(async () => release(json(result.body, result.status)))
    expect(await screen.findByText('Apstiprinātas kompetences: 1.')).toBeTruthy()
    expect(io.applies()).toHaveLength(1)
  })
})

describe('bulk verification: no way around the preview', () => {
  it('the card offers no apply control outside the preview dialog', async () => {
    serve(standard())
    renderCard()
    await openSelection()
    await userEvent.click(box(/W071/))
    expect(screen.queryByRole('button', { name: /Apstiprināt atlasītās/ })).toBeNull()
  })

  it('the API client applies only an applicable preview, built from its items', async () => {
    const fetchMock = vi.fn(async () => json({}))
    vi.stubGlobal('fetch', fetchMock)
    const blocked: BulkPreview = {
      applicable: false,
      items: [
        { service_id: 's1', w_id: 'W071', name: 'A', status: 'declared', expected_version: 1, verifiable: true, reasons: [] },
        { service_id: 's3', w_id: 'W073', name: 'B', status: 'declared', expected_version: 1, verifiable: false, reasons: [REGULATED] },
      ],
    }
    expect(() => adminMastersApi.bulkVerify('m1', blocked)).toThrow()
    expect(fetchMock).not.toHaveBeenCalled()

    await adminMastersApi.bulkVerify('m1', { applicable: true, items: [blocked.items[0]] })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(APPLY)
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ items: [{ service_id: 's1', expected_version: 1 }], confirm: true })
  })

  it('the preview call sends only the selected IDs', async () => {
    const fetchMock = vi.fn(async () => json({ items: [], applicable: true }))
    vi.stubGlobal('fetch', fetchMock)
    await adminMastersApi.bulkPreview('m1', ['s1', 's2'])
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(PREVIEW)
    expect(JSON.parse(String(init.body))).toEqual({ service_ids: ['s1', 's2'] })
  })
})
