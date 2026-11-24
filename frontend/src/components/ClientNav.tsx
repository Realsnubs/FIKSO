import { NavLink } from 'react-router'
import { t } from '../i18n/lv'

export function ClientNav() {
  return (
    <nav aria-label={t.clientNav.label} className="subnav">
      <NavLink to="/pakalpojumi">{t.clientNav.services}</NavLink>
      <NavLink to="/client" end>
        {t.clientNav.requests}
      </NavLink>
    </nav>
  )
}
