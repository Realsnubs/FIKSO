import { useEffect, useState } from 'react'
import type { Language } from '../i18n/language'
import { ApiError } from '../api/client'
import { publicApi } from '../api/work'
import type {
  Localized,
  PublicCatalogue,
  PublicCategory,
  PublicService,
  PublicSpecialisation,
  SpecialisationContent,
} from '../types/publicCatalogue'
import type { PublicCatalogueApi, PublicTerms, SpecialisationPageApi } from '../types/work'

/** Latvian source plus any approved translations from an API map (missing ones are simply absent). */
function toLocalized(lv: string, other?: Partial<Record<'lv' | 'en' | 'ru', string | undefined>> | null): Localized {
  const result: Localized = { lv: other?.lv || lv }
  if (other?.en) result.en = other.en
  if (other?.ru) result.ru = other.ru
  return result
}

function fromApi(api: PublicCatalogueApi): PublicCatalogue {
  return {
    demo: false,
    categories: api.categories.map((category) => ({
      id: category.id,
      name: toLocalized(category.name.lv, category.name),
      specialisations: category.specialisations.map((spec) => ({
        id: spec.slug,
        categoryId: category.id,
        name: toLocalized(spec.name.lv, spec.name),
        description: spec.description ? toLocalized(spec.description.lv, spec.description) : null,
        status: spec.status,
        services: spec.services.map((service) => ({
          id: service.id,
          wId: service.w_id,
          name: toLocalized(service.name.lv, service.name),
          orderable: true,
          description: service.description?.lv ? toLocalized(service.description.lv, service.description) : undefined,
        })),
        content:
          spec.lead || spec.card_image
            ? {
                lead: spec.lead?.lv ? toLocalized(spec.lead.lv, spec.lead) : undefined,
                cardImage: spec.card_image
                  ? { src: spec.card_image.urls['800'], alt: toLocalized(spec.card_image.alt.lv ?? '', spec.card_image.alt) }
                  : undefined,
              }
            : null,
        backendId: spec.id,
      })),
    })),
  }
}

/** Page content of one specialisation from the API, in the shape the page renders. */
export function contentFromApi(page: SpecialisationPageApi): SpecialisationContent {
  const texts = page.texts
  const lv = texts.lv ?? {}
  const pick = (key: 'title' | 'lead'): Localized | undefined =>
    lv[key] ? toLocalized(lv[key] as string, { en: texts.en?.[key], ru: texts.ru?.[key] }) : undefined
  const list = (key: 'can_do' | 'prepare'): Localized[] | undefined => {
    const items = lv[key] ?? []
    return items.length ? items.map((item, i) => toLocalized(item, { en: texts.en?.[key]?.[i], ru: texts.ru?.[key]?.[i] })) : undefined
  }
  const faq = (lv.faq ?? []).map((pair, i) => ({
    question: toLocalized(pair.q, { en: texts.en?.faq?.[i]?.q, ru: texts.ru?.faq?.[i]?.q }),
    answer: toLocalized(pair.a, { en: texts.en?.faq?.[i]?.a, ru: texts.ru?.faq?.[i]?.a }),
  }))
  return {
    title: pick('title'),
    lead: pick('lead'),
    canDo: list('can_do'),
    prepare: list('prepare'),
    faq: faq.length ? faq : undefined,
    photos: page.gallery.length
      ? page.gallery.map((image) => ({
          src: image.urls['800'],
          alt: toLocalized(image.alt.lv ?? image.caption.lv ?? '', image.alt),
          caption: toLocalized(image.caption.lv ?? '', image.caption),
          kind: image.kind,
        }))
      : undefined,
    cardImage: page.card_image
      ? { src: page.card_image.urls['800'], alt: toLocalized(page.card_image.alt.lv ?? '', page.card_image.alt) }
      : undefined,
  }
}

/**
 * The one source of the client catalogue: the public API (only orderable services, OQ-4). With
 * VITE_CATALOGUE_DEMO=true at build/dev time it loads the isolated demo layer instead (never in a normal build).
 * `null` means the catalogue could not be loaded (the pages say so honestly).
 */
export async function loadPublicCatalogue(): Promise<PublicCatalogue | null> {
  if (import.meta.env.VITE_CATALOGUE_DEMO === 'true') {
    const { demoCatalogue } = await import('../demo/catalogue')
    return demoCatalogue
  }
  // A network/server error rejects (the page says so); an empty catalogue resolves to null ("not published").
  const api = await publicApi.catalogue().catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  })
  if (!api) return null
  const catalogue = fromApi(api)
  return catalogue.categories.length ? catalogue : null
}

export function usePublicCatalogue(): { catalogue: PublicCatalogue | null; loading: boolean; failed: boolean } {
  const [state, setState] = useState<{ catalogue: PublicCatalogue | null; loading: boolean; failed: boolean }>({
    catalogue: null,
    loading: true,
    failed: false,
  })
  useEffect(() => {
    let cancelled = false
    loadPublicCatalogue().then(
      (catalogue) => !cancelled && setState({ catalogue, loading: false, failed: false }),
      () => !cancelled && setState({ catalogue: null, loading: false, failed: true }),
    )
    return () => {
      cancelled = true
    }
  }, [])
  return state
}

/** Full page content of a specialisation from the API (null in demo mode: the demo layer carries its own). */
export function useSpecialisationContent(slug: string, enabled: boolean): SpecialisationContent | null {
  const [content, setContent] = useState<SpecialisationContent | null>(null)
  useEffect(() => {
    if (!enabled || !slug) return
    let cancelled = false
    publicApi.specialisation(slug).then(
      (page) => !cancelled && setContent(contentFromApi(page)),
      () => !cancelled && setContent(null),
    )
    return () => {
      cancelled = true
    }
  }, [slug, enabled])
  return content
}

/** The public terms (rate, minimum, materials line) from the API, falling back to the confirmed values. */
export function usePublicTerms(language: Language): PublicTerms | null {
  const [terms, setTerms] = useState<PublicTerms | null>(null)
  useEffect(() => {
    if (import.meta.env.VITE_CATALOGUE_DEMO === 'true') return
    let cancelled = false
    publicApi.terms(language).then(
      (value) => !cancelled && setTerms(value),
      () => undefined,
    )
    return () => {
      cancelled = true
    }
  }, [language])
  return terms
}

/** The text in the chosen language, or the Latvian source when no approved translation exists. */
export function localized(value: Localized, language: Language): string {
  return value[language] ?? value.lv
}

export function orderableServices(spec: PublicSpecialisation): PublicService[] {
  return spec.status === 'active' ? spec.services.filter((s) => s.orderable) : []
}

/** Specialisations a client can order now: active, with at least one orderable service. Drafts never count. */
export function availableSpecialisations(category: PublicCategory): PublicSpecialisation[] {
  return category.specialisations.filter((s) => orderableServices(s).length > 0)
}

export function plannedSpecialisations(catalogue: PublicCatalogue): PublicSpecialisation[] {
  return catalogue.categories.flatMap((c) => c.specialisations.filter((s) => s.status === 'planned'))
}

export function findSpecialisation(catalogue: PublicCatalogue, id: string) {
  for (const category of catalogue.categories) {
    const spec = category.specialisations.find((s) => s.id === id)
    if (spec) return { category, spec }
  }
  return null
}

/** The orderable service with this W-ID, with its specialisation and category (deep links, order start). */
export function findOrderable(catalogue: PublicCatalogue, wId: string) {
  for (const category of catalogue.categories) {
    for (const spec of category.specialisations) {
      const service = orderableServices(spec).find((s) => s.wId === wId)
      if (service) return { category, spec, service }
    }
  }
  return null
}

/** The order start for one service: the W-ID travels in the URL, so it survives sign-in (returnTo, R-WEB-02). */
export function orderLink(wId: string): string {
  return `/pieteikums/jauns?w=${encodeURIComponent(wId)}`
}

/** Entry source of a deep link: `src=web` from the website survives sign-in in the URL (owner decision). */
export function entrySource(search: URLSearchParams): 'web' | undefined {
  return search.get('src') === 'web' ? 'web' : undefined
}
