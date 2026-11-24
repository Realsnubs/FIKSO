// Mirrors backend schemas in backend/app/schemas (OpenAPI: /api/v1/openapi.json).

export type Role = 'client' | 'master' | 'admin'
export type UserStatus = 'active' | 'blocked'
export type MasterApprovalStatus = 'pending_approval' | 'approved' | 'rejected'

export interface User {
  id: string
  role: Role
  email: string
  full_name: string
  phone: string | null
  status: UserStatus
  /** False for a client who ordered without registering (no password yet). */
  has_password: boolean
  master_approval_status: MasterApprovalStatus | null
  created_at: string
}

export interface AdminUser extends User {
  blocked_reason: string | null
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

/** Ordering without registering: the client account is created from the contact details alone. */
export type GuestPayload = Omit<RegisterPayload, 'password'>

export interface RegisterPayload {
  email: string
  password: string
  full_name: string
  phone: string
}
