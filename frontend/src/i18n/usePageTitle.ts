import { useEffect } from 'react'

/** The browser tab title: "<page> · FIKSO". Re-runs with the text, so a language switch updates it too. */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · FIKSO` : 'FIKSO'
  }, [title])
}
