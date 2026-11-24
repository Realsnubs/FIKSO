import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './App'
import { AuthContext, type AuthState } from './auth/context'
import type { Role, User } from './types/api'

// Every role-guarded route against every role (UI convenience only — the API enforces roles itself).

const ADMIN_ROUTES = [
  '/admin',
  '/admin/users',
  '/admin/masters',
  '/admin/masters/m1',
  '/admin/review-queue',
  '/admin/catalogue',
  '/admin/catalogue/qualifications',
  '/admin/catalogue/transfer',
  '/admin/content',
  '/admin/content/s1',
  '/admin/media',
  '/admin/terms',
  '/admin/commission',
  '/admin/commission/m1',
  '/admin/requests',
  '/admin/requests/r1',
]
const MASTER_ROUTES = ['/master', '/master/capabilities', '/master/darbs', '/master/komisija', '/master/pasutijumi/o1']
const CLIENT_ROUTES = ['/client', '/client/pieteikumi/r1']

const HOME: Record<Role, string> = { admin: 'Pārskats', master: 'Meistara panelis', client: 'Mani pieteikumi' }

function user(role: Role): User {
  return {
    id: 'u1',
    role,
    email: 'x@example.lv',
    full_name: 'Testa Lietotājs',
    phone: null,
    status: 'active',
    master_approval_status: role === 'master' ? 'approved' : null,
    has_password: true,
    created_at: '2026-10-01T09:00:00Z',
  }
}

function auth(current: User | null): AuthState {
  const noop = async () => {
    throw new Error('not used')
  }
  return { user: current, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

/** Records the API paths a page requests; answers 404 so no page gets data. */
function stubApi() {
  const paths: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      paths.push(new URL(input, 'http://localhost').pathname)
      return new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'x' } }), { status: 404 })
    }),
  )
  return paths
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

afterEach(() => vi.unstubAllGlobals())

const cases: [string, Role][] = [
  ...ADMIN_ROUTES.map((p) => [p, 'admin'] as [string, Role]),
  ...MASTER_ROUTES.map((p) => [p, 'master'] as [string, Role]),
  ...CLIENT_ROUTES.map((p) => [p, 'client'] as [string, Role]),
]

describe('route guards', () => {
  for (const [path, owner] of cases) {
    for (const other of (['admin', 'master', 'client'] as Role[]).filter((r) => r !== owner)) {
      it(`${path} sends a ${other} to their own area without calling the ${owner} API`, async () => {
        const paths = stubApi()
        renderAt(path, user(other))
        expect(await screen.findByRole('heading', { level: 1, name: HOME[other] })).toBeTruthy()
        expect(paths.filter((p) => p.startsWith(`/api/v1/${owner}`))).toEqual([])
      })
    }

    it(`${path} sends an anonymous visitor to login and requests nothing`, async () => {
      const paths = stubApi()
      renderAt(path, null)
      expect(await screen.findByRole('button', { name: 'Pieslēgties' })).toBeTruthy()
      expect(paths).toEqual([])
    })
  }

  it('the master area only ever calls the master API', async () => {
    const paths = stubApi()
    renderAt('/master/capabilities', user('master'))
    await screen.findByRole('alert')
    expect(paths.length).toBeGreaterThan(0)
    expect(paths.every((p) => p.startsWith('/api/v1/master/'))).toBe(true)
  })
})
