import { NavLink } from 'react-router'
import { t } from '../i18n/lv'

export function MasterNav() {
  return (
    <nav aria-label={t.capabilities.nav} className="subnav">
      <NavLink to="/master" end>
        {t.capabilities.home}
      </NavLink>
      <NavLink to="/master/darbs" end>
        {t.app.work.nav}
      </NavLink>
      <NavLink to="/master/komisija" end>
        {t.app.work.commissionNav}
      </NavLink>
      <NavLink to="/master/capabilities" end>
        {t.capabilities.title}
      </NavLink>
    </nav>
  )
}
