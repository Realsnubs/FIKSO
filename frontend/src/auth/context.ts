import { createContext, useContext } from 'react'
import type { GuestPayload, RegisterPayload, Role, User } from '../types/api'

export interface AuthState {
  user: User | null
  ready: boolean
  login: (email: string, password: string) => Promise<User>
  register: (role: 'client' | 'master', data: RegisterPayload) => Promise<User>
  logout: () => Promise<void>
  startGuest: (data: GuestPayload) => Promise<User>
  loginWithCode: (phone: string, code: string) => Promise<User>
  setPassword: (password: string, currentPassword?: string) => Promise<User>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export function homePath(role: Role): string {
  return `/${role}`
}

/** Only same-app paths are allowed as post-login redirects (prevents open redirects). */
export function safeReturnTo(value: string | null): string | null {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : null
}
