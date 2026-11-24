import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { applySession, onSessionChange, refreshSession, updateSessionUser } from '../api/client'
import { authApi } from '../api/endpoints'
import type { GuestPayload, RegisterPayload, User } from '../types/api'
import { AuthContext, type AuthState } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    onSessionChange(setUser)
    // Restore the session from the refresh cookie on page load.
    void refreshSession().finally(() => setReady(true))
    return () => onSessionChange(null)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    return applySession(await authApi.login(email, password)) as User
  }, [])

  const register = useCallback(async (role: 'client' | 'master', data: RegisterPayload) => {
    return applySession(await authApi.register(role, data)) as User
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      applySession(null)
    }
  }, [])

  const startGuest = useCallback(async (data: GuestPayload) => {
    return applySession(await authApi.guest(data)) as User
  }, [])

  const loginWithCode = useCallback(async (phone: string, code: string) => {
    return applySession(await authApi.verifySmsCode(phone, code)) as User
  }, [])

  const setPassword = useCallback(async (password: string, currentPassword?: string) => {
    const updated = await authApi.setPassword(password, currentPassword)
    updateSessionUser(updated)
    return updated
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, ready, login, register, logout, startGuest, loginWithCode, setPassword }),
    [user, ready, login, register, logout, startGuest, loginWithCode, setPassword],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
