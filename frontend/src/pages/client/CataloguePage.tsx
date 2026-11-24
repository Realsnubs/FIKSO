import { useEffect, useState } from 'react'
import { publicApi } from '../../api/work'
import { ClientNav } from '../../components/ClientNav'
import { Skeleton } from '../../components/Skeleton'
import { useAuth } from '../../auth/context'
import {
  availableSpecialisations,
  localized,
  plannedSpecialisations,
  usePublicCatalogue,
} from '../../catalogue/publicCatalogue'
import { t } from '../../i18n/lv'
import { useLanguage } from '../../i18n/LanguageContext'
import { usePageTitle } from '../../i18n/usePageTitle'
import { DemoBanner, PriceCard, SpecialisationCard } from './parts'

const ts = t.shop

/** "Pakalpojumi": the public catalogue, open to guests (owner decision 2026-11-04). */
export function CataloguePage() {
  usePageTitle(t.header.services)
  const { user } = useAuth()
  const { language } = useLanguage()
  const { catalogue, loading, failed } = usePublicCatalogue()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const live = Boolean(catalogue && !catalogue.demo)
  useEffect(() => {
    if (live) publicApi.event('catalogue_view').catch(() => undefined)
  }, [live])

  const q = query.trim().toLocaleLowerCase()
  const text = (value: { lv: string; en?: string; ru?: string } | null) =>
    value ? localized(value, language).toLocaleLowerCase() : ''
  const categories = (catalogue?.categories ?? [])
    .map((c) => ({ category: c, specs: availableSpecialisations(c) }))
    .filter((c) => c.specs.length > 0)
  const shown = categories
    .filter((c) => !category || c.category.id === category)
    .flatMap((c) =>
      c.specs
        .filter(
          (s) =>
            !q ||
            text(s.name).includes(q) ||
            text(s.description).includes(q) ||
            s.services.some((svc) => svc.orderable && (text(svc.name).includes(q) || svc.wId.toLowerCase() === q)),
        )
        .map((spec) => ({ spec, category: c.category })),
    )
  const planned = catalogue ? plannedSpecialisations(catalogue) : []

  return (
    <section>
      {user?.role === 'client' && <ClientNav />}
      {catalogue?.demo && <DemoBanner />}
      <section className="client-hero">
        <p className="eyebrow">{ts.eyebrow}</p>
        <h1>{ts.title}</h1>
        <p className="lead">{ts.lead}</p>
        {categories.length > 0 && (
          <form className="search" role="search" onSubmit={(e) => e.preventDefault()}>
            <label htmlFor="svc-search" className="visually-hidden">
              {ts.search}
            </label>
            <input
              id="svc-search"
              type="search"
              value={query}
              placeholder={ts.searchPlaceholder}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
        )}
      </section>

      {loading && <Skeleton variant="cards" />}

      {!loading && categories.length === 0 && (
        <div className="card stack">
          <h2>{failed ? t.errors.generic : ts.unavailableTitle}</h2>
          {!failed && <p className="muted">{ts.unavailableText}</p>}
          <PriceCard />
        </div>
      )}

      {categories.length > 1 && (
        <div className="chips" role="group" aria-label={ts.categoryFilter}>
          <button type="button" aria-pressed={category === null} onClick={() => setCategory(null)}>
            {ts.all}
          </button>
          {categories.map(({ category: c, specs }) => (
            <button key={c.id} type="button" aria-pressed={category === c.id} onClick={() => setCategory(c.id)}>
              {localized(c.name, language)} <span className="count">{specs.length}</span>
            </button>
          ))}
        </div>
      )}

      {categories.length > 0 && shown.length === 0 && <p className="empty">{ts.noResults}</p>}
      {shown.length > 0 && (
        <ul className="svc-grid" aria-label={t.header.services}>
          {shown.map(({ spec, category: c }) => (
            <SpecialisationCard key={spec.id} spec={spec} category={c} />
          ))}
        </ul>
      )}

      {planned.length > 0 && (
        <section className="soon" aria-labelledby="soon-title">
          <h2 id="soon-title">{ts.soonTitle}</h2>
          <p className="muted">{ts.soonHint}</p>
          <ul aria-label={ts.soonTitle}>
            {planned.map((s) => (
              <li key={s.id}>{localized(s.name, language)}</li>
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}
