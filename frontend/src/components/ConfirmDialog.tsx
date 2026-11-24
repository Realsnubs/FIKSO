import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { t } from '../i18n/lv'
import { restoreFocus } from './focus'

/**
 * A modal confirmation for a final decision (also the frame of the bulk verification preview): nothing is sent
 * until the confirm button is pressed. While the request runs both buttons are disabled and Escape does nothing;
 * focus stays inside and returns to the opener (or the main content when the opener is gone).
 */
export function ConfirmDialog({
  title,
  text,
  children,
  confirmLabel,
  busy,
  confirmDisabled = false,
  confirmTone = 'danger',
  narrow = false,
  onConfirm,
  onCancel,
}: {
  title: string
  text?: string
  children?: ReactNode
  confirmLabel: string
  busy: boolean
  /** E.g. while there is nothing (or nothing valid) to confirm. */
  confirmDisabled?: boolean
  /** Final or destructive decisions are `danger`; an ordinary submission is `primary`. */
  confirmTone?: 'danger' | 'primary'
  narrow?: boolean
  onConfirm: () => Promise<void>
  onCancel: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    return () => restoreFocus(opener)
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !busy) {
      event.stopPropagation()
      onCancel()
      return
    }
    if (event.key !== 'Tab' || !dialogRef.current) return
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled])'))
    if (focusable.length === 0) {
      event.preventDefault()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className={narrow ? 'dialog dialog-narrow' : 'dialog'}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby={text ? 'confirm-text' : undefined}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <h2 id="confirm-title">{title}</h2>
        {text && <p id="confirm-text">{text}</p>}
        {children}
        <div className="actions">
          <button
            type="button"
            className={confirmTone === 'danger' ? 'button-danger' : undefined}
            aria-busy={busy}
            disabled={busy || confirmDisabled}
            onClick={() => void onConfirm()}
          >
            {busy ? t.masterCard.saving : confirmLabel}
          </button>
          <button type="button" className="button-secondary" disabled={busy} onClick={onCancel}>
            {t.admin.cancel}
          </button>
        </div>
      </div>
    </div>
  )
}
