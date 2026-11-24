import { t } from '../i18n/lv'

/**
 * Loading placeholder: the page's rough shape instead of a bare "Ielādē…". Screen readers still hear the loading
 * text (role="status"); the blocks themselves are hidden from them.
 */
export function Skeleton({ variant = 'list' }: { variant?: 'list' | 'cards' | 'page' }) {
  const blocks = variant === 'page' ? 2 : 3
  return (
    <div role="status" className="skeleton">
      <span className="visually-hidden">{t.loading}</span>
      {variant === 'page' && <div className="bone title" aria-hidden="true" />}
      <div className="bone short" aria-hidden="true" />
      {Array.from({ length: blocks }, (_, i) => (
        <div key={i} className="bone block" aria-hidden="true" />
      ))}
    </div>
  )
}
