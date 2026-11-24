import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest, applySession } from './client'

const user = {
  id: '1',
  role: 'client',
  email: 'c@example.com',
  full_name: 'K',
  phone: null,
  status: 'active',
  master_approval_status: null,
  has_password: true,
  created_at: '2026-10-30T10:00:00Z',
} as const

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  applySession(null)
})

describe('apiRequest', () => {
  it('refreshes an expired access token once and retries the call', async () => {
    applySession({ access_token: 'old', token_type: 'bearer', expires_in: 900, user })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: 'NOT_AUTHENTICATED', message: 'x' } }))
      .mockResolvedValueOnce(json(200, { access_token: 'new', token_type: 'bearer', expires_in: 900, user }))
      .mockResolvedValueOnce(json(200, user))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest('/me')).resolves.toEqual(user)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/refresh')
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer new')
  })

  it('maps the backend error envelope to ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json(409, { error: { code: 'EMAIL_TAKEN', message: 'taken', details: {} } })),
    )
    const error = await apiRequest('/auth/register/client', { method: 'POST', body: {} }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'EMAIL_TAKEN' })
  })
})
