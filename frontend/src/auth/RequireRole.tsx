import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { Skeleton } from '../components/Skeleton'
import type { Role } from '../types/api'
import { homePath, useAuth } from './context'

/** UI convenience only: the backend enforces roles on every endpoint. */
export function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()

  if (!ready) return <Skeleton variant="page" />
  if (!user) {
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?returnTo=${returnTo}`} replace />
  }
  if (user.role !== role) return <Navigate to={homePath(user.role)} replace />
  return children
}

/** Guests and clients may order (owner decision 2026-11-24); masters and admins go to their own area. */
export function ClientOrGuest({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  if (!ready) return <Skeleton variant="page" />
  if (user && user.role !== 'client') return <Navigate to={homePath(user.role)} replace />
  return children
}
