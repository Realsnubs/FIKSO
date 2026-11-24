import { NavLink } from 'react-router'
import { t } from '../i18n/lv'

const links: { to: string; label: string; end: boolean }[] = [
  { to: '/admin', label: 'overview', end: true },
  { to: '/admin/requests', label: 'requestsNav', end: false },
  { to: '/admin/commission', label: 'commissionNav', end: false },
  { to: '/admin/users', label: 'users', end: true },
  { to: '/admin/masters', label: 'masters', end: true },
  { to: '/admin/review-queue', label: 'reviewQueue', end: true },
  { to: '/admin/catalogue', label: 'catalogue', end: true },
  { to: '/admin/catalogue/qualifications', label: 'qualifications', end: false },
  { to: '/admin/catalogue/transfer', label: 'transfer', end: false },
  { to: '/admin/content', label: 'contentNav', end: false },
  { to: '/admin/media', label: 'mediaNav', end: true },
  { to: '/admin/terms', label: 'termsNav', end: true },
]

function label(key: string): string {
  const own = t.adminNav as Record<string, string>
  const app = t.app.admin as unknown as Record<string, string>
  return own[key] ?? app[key]
}

export function AdminNav() {
  return (
    <nav aria-label={t.adminNav.label} className="subnav">
      {links.map((link) => (
        <NavLink key={link.to} to={link.to} end={link.end}>
          {label(link.label)}
        </NavLink>
      ))}
    </nav>
  )
}
