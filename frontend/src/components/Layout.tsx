import { Link, Outlet, useNavigate } from 'react-router'
import { useAuth } from '../auth/context'
import { t } from '../i18n/lv'
import { LanguageSwitcher } from './LanguageSwitcher'
import { ThemeToggle } from './ThemeToggle'

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <a className="skip-link" href="#main">
        {t.skipToContent}
      </a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label={t.brand.home}>
          <img className="logo-on-light" src="/brand/fikso-logo.webp" alt="" width={103} height={32} />
          <img className="logo-on-dark" src="/brand/fikso-logo-white.webp" alt="" width={103} height={32} />
        </Link>
        <div className="topbar-tools">
          {user && (
            <span className="topbar-user" title={`${user.full_name} · ${t.roles[user.role]}`}>
              {user.full_name} · {t.roles[user.role]}
            </span>
          )}
          <LanguageSwitcher />
          <ThemeToggle />
          {user ? (
            <button type="button" className="button-secondary button-small" onClick={handleLogout}>
              {t.logout}
            </button>
          ) : (
            // A guest browses the catalogue; signing in is a page, so it is a link.
            <Link to="/login" className="header-link">
              {t.header.login}
            </Link>
          )}
        </div>
      </header>
      <main id="main" className="container" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="site-footer-inner">
          <img src="/brand/fikso-logo-white.webp" alt={t.appName} width={90} height={28} />
          <span>{t.brand.footer}</span>
        </div>
      </footer>
    </>
  )
}
