/// <reference types="node" />
// Node's fs reads the stylesheet and index.html as text (Vitest does not load CSS, even with `?raw`).
import { readFileSync } from 'node:fs'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { AuthContext, type AuthState } from '../auth/context'
import type { User } from '../types/api'
import { THEME_KEY } from './theme'

// Vitest runs from the frontend root (vite.config.ts).
const css = readFileSync('src/index.css', 'utf8')
const html = readFileSync('index.html', 'utf8')

const anonymous: AuthState = {
  user: null,
  ready: true,
  login: async () => {
    throw new Error('not used')
  },
  register: async () => {
    throw new Error('not used')
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
}

/** The system preference as `matchMedia` reports it; `change` events can be fired by the test. */
function systemPrefers(dark: boolean) {
  const listeners: ((e: MediaQueryListEvent) => void)[] = []
  const media = {
    matches: dark,
    addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.push(fn),
    removeEventListener: vi.fn(),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  return (nowDark: boolean) => listeners.forEach((fn) => fn({ matches: nowDark } as MediaQueryListEvent))
}

function renderAt(path: string, auth: AuthState = anonymous) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 404 })))
  return render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

const toDark = () => screen.getByRole('button', { name: 'Ieslēgt tumšo režīmu' })
const toLight = () => screen.getByRole('button', { name: 'Ieslēgt gaišo režīmu' })

beforeEach(() => {
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('theme switch', () => {
  it('follows the system theme on the first visit, without storing anything', () => {
    systemPrefers(true)
    renderAt('/login')
    expect(toLight()).toBeTruthy() // the page is dark, so the switch offers light
    expect(document.documentElement.dataset.theme).toBeUndefined() // CSS follows the system by itself
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
  })

  it('tracks a system change while the user has not chosen', async () => {
    const change = systemPrefers(false)
    renderAt('/login')
    expect(toDark()).toBeTruthy()
    change(true)
    expect(await screen.findByRole('button', { name: 'Ieslēgt gaišo režīmu' })).toBeTruthy()
  })

  it('switching applies the theme at once and remembers it', async () => {
    systemPrefers(false)
    renderAt('/login')
    await userEvent.click(toDark())
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    await userEvent.click(toLight())
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
  })

  it('a stored choice wins over the system theme after a reload', () => {
    systemPrefers(true)
    localStorage.setItem(THEME_KEY, 'light')
    renderAt('/login')
    expect(toDark()).toBeTruthy()
  })

  it('works when storage is unavailable (the choice then lasts for the page only)', async () => {
    systemPrefers(false)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    renderAt('/login')
    await userEvent.click(toDark())
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('is in the header on every page, for every role', () => {
    systemPrefers(false)
    const master: User = {
      id: 'u1',
      role: 'master',
      email: 'm@example.lv',
      full_name: 'Meistars',
      phone: null,
      status: 'active',
      master_approval_status: 'approved',
      has_password: true,
      created_at: '2026-10-01T09:00:00Z',
    }
    const { unmount } = renderAt('/login')
    expect(screen.getByRole('banner').contains(toDark())).toBe(true)
    unmount()
    renderAt('/master', { ...anonymous, user: master })
    expect(screen.getByRole('banner').contains(toDark())).toBe(true)
  })

  it('index.html applies a stored choice before the first paint and ignores anything else', () => {
    const script = /<script>([\s\S]*?)<\/script>/.exec(html)?.[1]
    expect(script).toBeTruthy()
    for (const [stored, expected] of [
      ['dark', 'dark'],
      ['light', 'light'],
      ['purple', undefined],
      [null, undefined],
    ] as const) {
      delete document.documentElement.dataset.theme
      localStorage.clear()
      if (stored) localStorage.setItem(THEME_KEY, stored)
      new Function(script!)()
      expect(document.documentElement.dataset.theme).toBe(expected)
    }
  })
})

describe('design tokens', () => {
  const block = (selector: string) => {
    const start = css.indexOf(selector)
    return css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start))
  }
  const declarations = (text: string) =>
    text
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .split(';')
      .map((d) => d.trim())
      .filter(Boolean)
      .sort()

  it('the dark palette is the same for the user choice and for the system preference', () => {
    const chosen = declarations(block(":root[data-theme='dark']"))
    const system = declarations(block(":root:not([data-theme='light'])"))
    expect(chosen.length).toBeGreaterThan(20)
    expect(system).toEqual(chosen)
  })

  it('both palettes define the same tokens', () => {
    const names = (text: string) => declarations(text).map((d) => d.split(':')[0]).filter((n) => n.startsWith('--'))
    const light = names(block(':root {'))
    const dark = names(block(":root[data-theme='dark']"))
    for (const token of ['--bg', '--surface', '--text', '--muted', '--border', '--primary', '--secondary', '--danger', '--success-fg', '--warning-fg', '--disabled-bg', '--disabled-text']) {
      expect(light).toContain(token)
      expect(dark).toContain(token)
    }
    const layout = ['--font', '--radius', '--radius-sm', '--control-height', '--shell'] // not colours: one value for both
    expect([...dark].sort()).toEqual(light.filter((n) => !layout.includes(n)).sort())
  })

  it('components use tokens only: no literal colours outside the palette blocks', () => {
    const withoutPalettes = css
      .replace(/:root \{[\s\S]*?\n\}/, '')
      .replace(/:root\[data-theme='dark'\] \{[\s\S]*?\n\}/, '')
      .replace(/@media \(prefers-color-scheme: dark\) \{[\s\S]*?\n\}\n/, '')
      .replace(/\/\*[\s\S]*?\*\//g, '')
    expect(withoutPalettes.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)).toBeNull()
  })
})
