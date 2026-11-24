/**
 * Where focus goes when a dialog closes: back to the control that opened it, or — when a decision removed that
 * control (e.g. an approved item has no approve button any more) — to the main content, so keyboard users are
 * not thrown back to the top of the document.
 */
export function restoreFocus(opener: HTMLElement | null): void {
  if (opener?.isConnected) opener.focus()
  else document.getElementById('main')?.focus()
}
