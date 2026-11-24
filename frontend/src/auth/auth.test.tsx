import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from '../pages/LoginPage'
import type { User } from '../types/api'
import { AuthContext, safeReturnTo, type AuthState } from './context'
import { RequireRole } from './RequireRole'

const noop = async () => {
  throw new Error('not used')
}

function authState(user: User | null): AuthState {
  return { user, ready: true, login: noop, register: noop, logout: async () => {}, startGuest: noop, loginWithCode: noop, setPassword: noop }
}

const client: User = {
  id: '1',
  role: 'client',
  email: 'c@example.com',
  full_name: 'Klients',
  phone: '+37120000000',
  status: 'active',
  master_approval_status: null,
  has_password: true,
  created_at: '2026-10-30T10:00:00Z',
}

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}

function renderAt(path: string, user: User | null) {
  render(
    <AuthContext.Provider value={authState(user)}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/admin"
            element={
              <RequireRole role="admin">
                <p>admin area</p>
              </RequireRole>
            }
          />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('RequireRole', () => {
  it('sends anonymous users to login and keeps the requested path', () => {
    renderAt('/admin?tab=x', null)
    expect(screen.getByTestId('where').textContent).toBe('/login?returnTo=%2Fadmin%3Ftab%3Dx')
  })

  it('sends users with another role to their own home', () => {
    renderAt('/admin', client)
    expect(screen.getByTestId('where').textContent).toBe('/client')
    expect(screen.queryByText('admin area')).toBeNull()
  })

  it('renders the area for the matching role', () => {
    renderAt('/admin', { ...client, role: 'admin' })
    expect(screen.getByText('admin area')).toBeTruthy()
  })
})

describe('safeReturnTo', () => {
  it.each([
    ['/order/new?w=W012', '/order/new?w=W012'],
    ['//evil.example', null],
    ['https://evil.example', null],
    [null, null],
  ])('%s -> %s', (input, expected) => {
    expect(safeReturnTo(input)).toBe(expected)
  })
})

describe('sign-in with an SMS code (clients who ordered without a password)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks for the phone, then the code, and signs in with both', async () => {
    const posted: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string, init?: RequestInit) => {
        posted.push({ url: String(input), body: JSON.parse(String(init?.body)) })
        return new Response('null', { status: 202 }) // FastAPI answers 202 with a JSON null
      }),
    )
    const loginWithCode = vi.fn(async () => client)
    render(
      <AuthContext.Provider value={{ ...authState(null), loginWithCode }}>
        <MemoryRouter initialEntries={['/login?returnTo=%2Fclient']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Pieslēgties ar SMS kodu' }))
    await userEvent.type(screen.getByLabelText('Tālrunis'), '+371 2000 0000')
    await userEvent.click(screen.getByRole('button', { name: 'Sūtīt kodu' }))
    expect(await screen.findByText(/Ja šim numuram ir klienta konts/)).toBeTruthy()
    expect(posted).toEqual([{ url: '/api/v1/auth/sms-code', body: { phone: '+37120000000' } }])
    await userEvent.type(screen.getByLabelText('Kods no SMS'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Pieslēgties' }))
    expect(loginWithCode).toHaveBeenCalledWith('+37120000000', '123456')
    expect((await screen.findByTestId('where')).textContent).toBe('/client')
  })
})
