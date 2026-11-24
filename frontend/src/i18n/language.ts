import { en } from './en'
import { lv, t, type Dict } from './lv'
import { ru } from './ru'

/**
 * Interface language: Latvian by default; English and Russian on the user's choice (owner decision 2026-11-04).
 * The choice is kept in localStorage like the theme. Catalogue names, reasons and other data stay as entered.
 */
export type Language = 'lv' | 'en' | 'ru'

export const LANGUAGES: { code: Language; name: string }[] = [
  { code: 'lv', name: 'Latviešu' },
  { code: 'en', name: 'English' },
  { code: 'ru', name: 'Русский' },
]
export const LANGUAGE_KEY = 'fikso-lang'

const DICTIONARIES: Record<Language, Dict> = { lv, en, ru }
const LOCALES: Record<Language, string> = { lv: 'lv-LV', en: 'en-GB', ru: 'ru-RU' }

let current: Language = 'lv'

function isLanguage(value: unknown): value is Language {
  return value === 'lv' || value === 'en' || value === 'ru'
}

/** The stored choice, or Latvian when there is none or storage is unavailable. */
export function storedLanguage(): Language {
  try {
    const value = window.localStorage.getItem(LANGUAGE_KEY)
    return isLanguage(value) ? value : 'lv'
  } catch {
    return 'lv'
  }
}

export function currentLanguage(): Language {
  return current
}

/** The locale dates are formatted in (still in Riga time). */
export function currentLocale(): string {
  return LOCALES[current]
}

/** Copies a dictionary into the live object graph, replacing every value and dropping keys it does not have. */
function assign(target: Record<string, unknown>, source: Record<string, unknown>): void {
  for (const key of Object.keys(target)) if (!(key in source)) delete target[key]
  for (const [key, value] of Object.entries(source)) {
    const existing = target[key]
    if (value && typeof value === 'object' && existing && typeof existing === 'object') {
      assign(existing as Record<string, unknown>, value as Record<string, unknown>)
    } else {
      target[key] = value
    }
  }
}

/** Switches the strings `t` serves and the document language; React re-renders from the App root. */
export function applyLanguage(language: Language): void {
  current = language
  assign(t as unknown as Record<string, unknown>, DICTIONARIES[language] as unknown as Record<string, unknown>)
  document.documentElement.lang = language
}

/** Applies and remembers the user's choice; without storage it lasts for this page only. */
export function chooseLanguage(language: Language): void {
  applyLanguage(language)
  try {
    window.localStorage.setItem(LANGUAGE_KEY, language)
  } catch {
    // Storage unavailable.
  }
}
