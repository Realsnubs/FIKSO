import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/context'
import { errorMessage, t } from '../i18n/lv'
import { Field } from './Field'

const tg = t.app.guest

/** Offered to a client who ordered without registering, so they can also sign in from other devices. */
export function SetPasswordCard() {
  const { user, setPassword } = useAuth()
  const [hidden, setHidden] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (saved) {
    return (
      <p className="notice" role="status">
        {tg.passwordSaved}
      </p>
    )
  }
  if (!user || user.has_password || hidden) return null

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const password = String(new FormData(event.currentTarget).get('password'))
    setSaving(true)
    setError(null)
    try {
      await setPassword(password)
      setSaved(true)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="set-password">
      <h2 id="set-password">{tg.setPasswordTitle}</h2>
      <p>{tg.setPasswordText}</p>
      <form className="stack" onSubmit={save}>
        <input type="email" name="username" autoComplete="username" value={user.email} readOnly hidden />
        <Field
          label={tg.newPassword}
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          hint={tg.passwordHint}
        />
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" aria-busy={saving || undefined} disabled={saving}>
            {tg.savePassword}
          </button>
          <button type="button" className="button-secondary" onClick={() => setHidden(true)}>
            {tg.later}
          </button>
        </div>
      </form>
    </section>
  )
}
