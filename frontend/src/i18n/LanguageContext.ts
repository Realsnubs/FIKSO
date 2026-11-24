import { createContext, useContext } from 'react'
import { chooseLanguage, currentLanguage, type Language } from './language'

interface LanguageState {
  language: Language
  setLanguage: (language: Language) => void
}

/**
 * The chosen language. App holds it as state, so a switch re-renders the whole tree (component state such as an
 * unsent form is kept). Without the App root (single pages in tests) a switch only changes the strings.
 */
export const LanguageContext = createContext<LanguageState>({
  language: currentLanguage(),
  setLanguage: chooseLanguage,
})

export function useLanguage(): LanguageState {
  return useContext(LanguageContext)
}
