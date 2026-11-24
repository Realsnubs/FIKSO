import type { TokenResponse, User } from '../types/api'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

// The access token lives only in memory; the refresh token is an HttpOnly cookie the browser sends itself.
let accessToken: string | null = null
let sessionListener: ((user: User | null) => void) | null = null
let refreshInFlight: Promise<User | null> | null = null

export function onSessionChange(listener: ((user: User | null) => void) | null): void {
  sessionListener = listener
}

export function applySession(tokens: TokenResponse | null): User | null {
  accessToken = tokens?.access_token ?? null
  const user = tokens?.user ?? null
  sessionListener?.(user)
  return user
}

/** Replaces the signed-in user's data (e.g. after setting a password) without touching the tokens. */
export function updateSessionUser(user: User): void {
  sessionListener?.(user)
}

/** Exchanges the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<User | null> {
  refreshInFlight ??= fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then(async (res) => applySession(res.ok ? ((await res.json()) as TokenResponse) : null))
    .catch(() => applySession(null))
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { ...options.headers }
  // Multipart (file uploads): the browser sets the Content-Type with its boundary itself.
  const form = options.body instanceof FormData
  if (options.body !== undefined && !form) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const res = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : form ? (options.body as FormData) : JSON.stringify(options.body),
    credentials: 'include',
  })

  if (res.status === 401 && retry && accessToken && !path.startsWith('/auth/')) {
    if (await refreshSession()) return apiRequest<T>(path, options, false)
  }
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export interface FileBlob {
  blob: Blob
  /** From Content-Disposition; null when the server sends none. */
  filename: string | null
}

/**
 * A private file through the authorised API (with the same token refresh and error model as JSON calls).
 * The caller turns it into a short-lived Blob URL and revokes it; no file link outlives the page.
 */
export async function apiBlob(path: string, retry = true): Promise<FileBlob> {
  const headers: Record<string, string> = {}
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const res = await fetch(`${BASE}${path}`, { method: 'GET', headers, credentials: 'include' })
  if (res.status === 401 && retry && accessToken) {
    if (await refreshSession()) return apiBlob(path, false)
  }
  if (!res.ok) throw await toApiError(res)
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? null
  return { blob: await res.blob(), filename }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string; details?: Record<string, unknown> } }
    if (body.error) return new ApiError(res.status, body.error.code, body.error.message, body.error.details)
  } catch {
    // Non-JSON error (proxy, network gateway): fall through to a generic error.
  }
  return new ApiError(res.status, 'HTTP_ERROR', res.statusText)
}
