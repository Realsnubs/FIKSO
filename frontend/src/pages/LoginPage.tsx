import { usePageTitle } from '../i18n/usePageTitle'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { homePath, safeReturnTo, useAuth } from '../auth/context'
import { Field } from '../components/Field'
import { authApi } from '../api/endpoints'
import { errorMessage, t } from '../i18n/lv'

const tg = t.app.guest

export function LoginPage() {
  usePageTitle(t.login.title)
  const { user, login, loginWithCode } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const returnTo = safeReturnTo(params.get('returnTo'))
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // Clients without a password (ordered as guests) sign in with a one-time SMS code.
  const [bySms, setBySms] = useState(false)
  const [smsPhone, setSmsPhone] = useState<string | null>(null)

  if (user) return <Navigate to={returnTo ?? homePath(user.role)} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSubmitting(true)
    setError(null)
    try {
      const loggedIn = await login(String(form.get('email')), String(form.get('password')))
      navigate(returnTo ?? homePath(loggedIn.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function requestCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const phone = String(new FormData(event.currentTarget).get('phone')).replace(/\s/g, '')
    setSubmitting(true)
    setError(null)
    try {
      await authApi.requestSmsCode(phone)
      setSmsPhone(phone)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function verifyCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!smsPhone) return
    const code = String(new FormData(event.currentTarget).get('code')).trim()
    setSubmitting(true)
    setError(null)
    try {
      const loggedIn = await loginWithCode(smsPhone, code)
      navigate(returnTo ?? homePath(loggedIn.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  function switchMode() {
    setBySms(!bySms)
    setSmsPhone(null)
    setError(null)
  }

  const errorLine = error && (
    <p role="alert" className="error">
      {error}
    </p>
  )

  const keepReturn = returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : ''
  return (
    <section className="card narrow">
      <h1>{t.login.title}</h1>
      {returnTo?.startsWith('/pieteikums/') && <p className="notice notice-pending_approval">{t.orderStart.loginHint}</p>}
      {!bySms && (
        <form onSubmit={handleSubmit}>
          <Field label={t.login.email} name="email" type="email" autoComplete="email" required />
          <Field
            label={t.login.password}
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
          {errorLine}
          <button type="submit" className="button-block" aria-busy={submitting} disabled={submitting}>
            {submitting ? t.loading : t.login.submit}
          </button>
        </form>
      )}
      {bySms && !smsPhone && (
        <form onSubmit={requestCode}>
          <Field
            label={tg.phone}
            name="phone"
            type="tel"
            autoComplete="tel"
            required
            pattern="\+[1-9][0-9 ]{7,17}"
            hint={t.register.phoneHint}
          />
          {errorLine}
          <button type="submit" className="button-block" aria-busy={submitting} disabled={submitting}>
            {submitting ? t.loading : tg.sendCode}
          </button>
        </form>
      )}
      {bySms && smsPhone && (
        <form onSubmit={verifyCode}>
          <p className="notice" role="status">
            {tg.codeSent}
          </p>
          <Field
            label={tg.code}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            pattern="[0-9]{6}"
            maxLength={6}
          />
          {errorLine}
          <button type="submit" className="button-block" aria-busy={submitting} disabled={submitting}>
            {submitting ? t.loading : tg.verify}
          </button>
          <button type="button" className="button-secondary button-block" onClick={() => setSmsPhone(null)}>
            {tg.resend}
          </button>
        </form>
      )}
      <p>
        <button type="button" className="button-ghost" onClick={switchMode}>
          {bySms ? tg.passwordLogin : tg.smsLogin}
        </button>
      </p>
      <p>
        {t.login.noAccount} <Link to={`/register/client${keepReturn}`}>{t.login.registerClient}</Link>
        {' · '}
        <Link to={`/register/master${keepReturn}`}>{t.login.registerMaster}</Link>
      </p>
    </section>
  )
}
