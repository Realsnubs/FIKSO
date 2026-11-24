/// <reference types="node" />
// Node's fs reads index.html as text.
import { readFileSync } from 'node:fs'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import App, { AppRoutes } from '../App'
import { AuthContext, type AuthState } from '../auth/context'
import type { Role, User } from '../types/api'
import { en } from './en'
import { rigaDate, rigaDateTime, rigaToday } from './format'
import { applyLanguage, currentLanguage, LANGUAGE_KEY, storedLanguage } from './language'
import { errorMessage, lv, t } from './lv'
import { ru } from './ru'

/** Every leaf path of a dictionary with its kind; functions also with their arity. */
function shape(value: unknown, path = ''): string[] {
  if (typeof value === 'function') return [`${path}:fn${value.length}`]
  if (typeof value === 'object' && value !== null) {
    return Object.entries(value).flatMap(([key, item]) => shape(item, path ? `${path}.${key}` : key))
  }
  return [`${path}:${typeof value}`]
}

function leaves(value: unknown, path = ''): [string, unknown][] {
  if (typeof value === 'object' && value !== null) {
    return Object.entries(value).flatMap(([key, item]) => leaves(item, path ? `${path}.${key}` : key))
  }
  return [[path, value]]
}

beforeEach(() => {
  localStorage.clear()
  applyLanguage('lv')
})

afterEach(() => {
  applyLanguage('lv')
  vi.unstubAllGlobals()
})

describe('dictionaries', () => {
  it('English and Russian have exactly the shape of Latvian (keys, kinds, function arities)', () => {
    const reference = shape(lv).sort()
    expect(reference.length).toBeGreaterThan(400)
    expect(shape(en).sort()).toEqual(reference)
    expect(shape(ru).sort()).toEqual(reference)
  })

  it('no text is empty, and every function returns text', () => {
    for (const dict of [lv, en, ru]) {
      for (const [path, value] of leaves(dict)) {
        if (typeof value === 'function') {
          const text = (value as (...a: unknown[]) => unknown)('X', 2)
          expect(typeof text, path).toBe('string')
          expect((text as string).length, path).toBeGreaterThan(0)
        } else {
          expect(typeof value, path).toBe('string')
          expect((value as string).trim().length, path).toBeGreaterThan(0)
        }
      }
    }
  })

  it('translations are really translated (apart from names, codes and shared terms)', () => {
    const same = (dict: typeof lv) =>
      leaves(dict).filter(([path, value]) => typeof value === 'string' && leaves(lv).find(([p]) => p === path)?.[1] === value)
    const allowed = ['appName', 'catalogueStatus.hold', 'capabilities.filesLabel', 'app.none', 'app.admin.media.bases.licence']
    expect(same(en).map(([p]) => p).filter((p) => !allowed.includes(p))).toEqual([])
    expect(same(ru).map(([p]) => p).filter((p) => !allowed.includes(p))).toEqual([])
  })
})

describe('language switch', () => {
  function startApp() {
    // No session, on the login page (a guest at "/" starts in the public catalogue).
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
    window.history.pushState({}, '', '/login')
    render(<App />)
  }

  it('Latvian is the default; switching changes the whole page, the document language and is remembered', async () => {
    startApp()
    expect(await screen.findByRole('heading', { level: 1, name: 'Pieslēgties' })).toBeTruthy()
    expect(document.documentElement.lang).toBe('lv')
    const switcher = screen.getByRole('group', { name: 'Valoda' })
    expect(within(switcher).getByRole('button', { name: 'Latviešu' }).getAttribute('aria-pressed')).toBe('true')

    await userEvent.click(within(switcher).getByRole('button', { name: 'English' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in' })).toBeTruthy()
    expect(screen.getByLabelText('Password')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Register as a client' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Language' })).toBeTruthy()
    expect(screen.getByText('© 2026 FIKSO · Riga and Pierīga')).toBeTruthy()
    expect(document.documentElement.lang).toBe('en')
    expect(localStorage.getItem(LANGUAGE_KEY)).toBe('en')

    await userEvent.click(screen.getByRole('button', { name: 'Русский' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Вход' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Войти' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Русский' }).getAttribute('aria-pressed')).toBe('true')
    expect(document.documentElement.lang).toBe('ru')
    expect(localStorage.getItem(LANGUAGE_KEY)).toBe('ru')

    await userEvent.click(screen.getByRole('button', { name: 'Latviešu' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Pieslēgties' })).toBeTruthy()
  })

  it('keeps what the user typed when the language changes', async () => {
    startApp()
    const email = (await screen.findByLabelText('E-pasts')) as HTMLInputElement
    await userEvent.type(email, 'janis@example.lv')
    await userEvent.click(screen.getByRole('button', { name: 'English' }))
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe('janis@example.lv')
  })

  it('the stored language is used at the next start; anything unknown falls back to Latvian', () => {
    localStorage.setItem(LANGUAGE_KEY, 'ru')
    expect(storedLanguage()).toBe('ru')
    localStorage.setItem(LANGUAGE_KEY, 'de')
    expect(storedLanguage()).toBe('lv')
    localStorage.clear()
    expect(storedLanguage()).toBe('lv')
  })

  it('works when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(storedLanguage()).toBe('lv')
    vi.restoreAllMocks()
  })

  it('module-level references (const tc = t.capabilities) follow the switch', () => {
    const tc = t.capabilities
    const reasons = t.decisionReasons
    applyLanguage('en')
    expect(currentLanguage()).toBe('en')
    expect(tc.title).toBe('My specialisations')
    expect(tc.withdrawText('Elektriķis')).toContain('will no longer be reviewed')
    expect(reasons.QUALIFICATION_MISSING).toBe('The required qualification is not approved')
    expect(errorMessage({ code: 'RATE_LIMITED' })).toBe('Too many attempts. Please try again later.')
    applyLanguage('ru')
    expect(tc.title).toBe('Мои специализации')
    expect(errorMessage({ code: 'NOPE' })).toBe('Произошла ошибка. Попробуйте ещё раз.')
    applyLanguage('lv')
    expect(tc.title).toBe('Manas specializācijas')
  })

  it('switching never changes the Latvian source dictionary', () => {
    applyLanguage('ru')
    expect(lv.login.title).toBe('Pieslēgties')
    expect(t.login.title).toBe('Вход')
  })

  it('dates follow the language and stay in Riga time', () => {
    const at = '2026-11-02T22:30:00Z' // 00:30 on 3 November in Riga
    applyLanguage('lv')
    const latvian = rigaDateTime(at)
    applyLanguage('en')
    const english = rigaDateTime(at)
    applyLanguage('ru')
    const russian = rigaDate(at)
    expect(english).not.toBe(latvian)
    expect(english).toMatch(/3 Nov 2026/)
    expect(english).toMatch(/00:30/)
    expect(russian).toMatch(/3 нояб/)
  })

  it('index.html applies a stored language before the first paint', () => {
    const html = readFileSync('index.html', 'utf8')
    const script = /<script>([\s\S]*?)<\/script>/.exec(html)?.[1]
    for (const [stored, expected] of [
      ['en', 'en'],
      ['ru', 'ru'],
      ['xx', 'lv'],
    ] as const) {
      document.documentElement.lang = 'lv'
      localStorage.setItem(LANGUAGE_KEY, stored)
      new Function(script!)()
      expect(document.documentElement.lang).toBe(expected)
    }
  })
})

describe('every page in every language', () => {
  const pages: [string, Role | null][] = [
    ['/login', null],
    ['/register/client', null],
    ['/register/master', null],
    ['/pakalpojumi', null],
    ['/pakalpojumi/cm-s07', null],
    ['/pieteikums/jauns?w=W092', 'client'],
    ['/client', 'client'],
    ['/master', 'master'],
    ['/master/capabilities', 'master'],
    ['/admin', 'admin'],
    ['/admin/users', 'admin'],
    ['/admin/masters', 'admin'],
    ['/admin/masters/m1', 'admin'],
    ['/admin/review-queue', 'admin'],
    ['/admin/catalogue', 'admin'],
    ['/admin/catalogue/qualifications', 'admin'],
    ['/admin/catalogue/transfer', 'admin'],
    ['/nowhere', null],
  ]
  const auth = (role: Role | null): AuthState => ({
    user: role
      ? ({ id: 'u1', role, email: 'x@example.lv', full_name: 'Testa Lietotājs', phone: null, status: 'active',
          master_approval_status: role === 'master' ? 'approved' : null, has_password: true, created_at: '2026-10-01T09:00:00Z' } as User)
      : null,
    ready: true,
    login: async () => {
      throw new Error('x')
    },
    register: async () => {
      throw new Error('x')
    },
    logout: async () => {},
    startGuest: async () => {
      throw new Error('not used')
    },
    loginWithCode: async () => {
      throw new Error('not used')
    },
    setPassword: async () => {
      throw new Error('not used')
    },
  })

  for (const language of ['en', 'ru'] as const) {
    it.each(pages)(`${language}: %s renders without missing texts`, async (path, role) => {
      applyLanguage(language)
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'x' } }), { status: 404 })))
      render(
        <AuthContext.Provider value={auth(role)}>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext.Provider>,
      )
      // A page title, or (with no data from the stubbed API) its error message.
      await waitFor(() => expect(document.querySelector('h1, [role="alert"]')).toBeTruthy())
      const text = document.body.textContent ?? ''
      expect(text).not.toMatch(/undefined|\[object Object\]/)
      // The language switcher always names the languages in themselves.
      expect(screen.getByRole('button', { name: 'Latviešu' })).toBeTruthy()
      expect(document.documentElement.lang).toBe(language)
    })
  }
})

describe('business date', () => {
  it('is the Riga calendar day, not the UTC one, just after midnight', () => {
    // 2026-11-04 22:40 UTC = 2026-11-05 00:40 in Riga (EET, UTC+2).
    expect(rigaToday(new Date('2026-11-04T22:40:00Z'))).toBe('2026-11-05')
    expect(rigaToday(new Date('2026-07-01T20:59:00Z'))).toBe('2026-07-01')
  })
})
