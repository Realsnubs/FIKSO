/**
 * Light/dark theme. The user's choice is kept in localStorage (it survives reloads, logout and login on this
 * device); without a choice the system preference applies. index.html applies a stored choice before the first
 * paint, so the page never flashes in the wrong theme.
 */
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'fikso-theme'

/** The stored choice; null when there is none or storage is unavailable (private mode, blocked storage). */
export function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Applies and remembers the user's choice. The theme still applies when storage fails; it is just not kept. */
export function chooseTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Storage unavailable: the choice lasts for this page only.
  }
}
