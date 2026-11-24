import { usePageTitle } from '../i18n/usePageTitle'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { homePath, safeReturnTo, useAuth } from '../auth/context'
import { Field } from '../components/Field'
import { errorMessage, t } from '../i18n/lv'

export function RegisterPage({ role }: { role: 'client' | 'master' }) {
  usePageTitle(role === 'client' ? t.register.titleClient : t.register.titleMaster)
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const returnTo = safeReturnTo(params.get('returnTo'))
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to={returnTo ?? homePath(user.role)} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSubmitting(true)
    setError(null)
    try {
      const created = await register(role, {
        full_name: String(form.get('full_name')),
        email: String(form.get('email')),
        phone: String(form.get('phone')).replace(/\s/g, ''),
        password: String(form.get('password')),
      })
      navigate(returnTo ?? homePath(created.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="card narrow">
      <h1>{role === 'client' ? t.register.titleClient : t.register.titleMaster}</h1>
      {returnTo?.startsWith('/pieteikums/') && <p className="notice notice-pending_approval">{t.orderStart.loginHint}</p>}
      <form onSubmit={handleSubmit}>
        <Field label={t.register.fullName} name="full_name" autoComplete="name" required maxLength={120} />
        <Field label={t.login.email} name="email" type="email" autoComplete="email" required />
        <Field
          label={t.register.phone}
          name="phone"
          type="tel"
          autoComplete="tel"
          required
          pattern="\+[1-9][0-9 ]{7,17}"
          hint={t.register.phoneHint}
        />
        <Field
          label={t.login.password}
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          hint={t.register.passwordHint}
        />
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button type="submit" className="button-block" aria-busy={submitting} disabled={submitting}>
          {submitting ? t.loading : t.register.submit}
        </button>
      </form>
      <p>
        {t.register.haveAccount} <Link to="/login">{t.login.submit}</Link>
      </p>
    </section>
  )
}
