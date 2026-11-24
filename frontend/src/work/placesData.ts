import { useEffect, useState } from 'react'
import { publicApi } from '../api/work'
import type { Language } from '../i18n/language'
import { errorMessage, t } from '../i18n/lv'
import type { CityApi, CommunicationLanguageApi } from '../types/work'

const tp = t.app.places
export const ANY_LANGUAGE = 'any'

interface Places {
  cities: CityApi[]
  languages: CommunicationLanguageApi[]
}

// Both lists are reference data that change only through an admin/migration; one load per page session is enough.
let cached: Promise<Places> | null = null

function loadPlaces(): Promise<Places> {
  cached ??= Promise.all([publicApi.cities(), publicApi.languages()])
    .then(([cities, languages]) => ({ cities, languages }))
    .catch((error: unknown) => {
      cached = null
      throw error
    })
  return cached
}

/** Test hook: forget the loaded lists. */
export function resetPlaces(): void {
  cached = null
}

export function usePlaces(): Places & { error: string | null; loading: boolean } {
  const [places, setPlaces] = useState<Places | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    loadPlaces().then(
      (value) => alive && setPlaces(value),
      (e: unknown) => alive && setError(errorMessage(e)),
    )
    return () => {
      alive = false
    }
  }, [])
  return { cities: places?.cities ?? [], languages: places?.languages ?? [], error, loading: !places && !error }
}

// Searching "rezekne" or "резекне" must find "Rēzekne": compare without case and diacritics.
function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
}

export function matches(query: string, ...texts: string[]): boolean {
  const q = fold(query.trim())
  return !q || texts.some((text) => fold(text).includes(q))
}

export function cityName(city: CityApi | null | undefined, language: Language): string {
  return city ? (city.name[language] ?? city.name.lv) : tp.none
}

export function languageName(code: string, languages: CommunicationLanguageApi[], language: Language): string {
  if (code === ANY_LANGUAGE) return tp.anyLanguage
  const found = languages.find((l) => l.code === code)
  if (!found) return code
  return `${found.flag ? `${found.flag} ` : ''}${found.name[language] ?? found.name.lv}`
}
