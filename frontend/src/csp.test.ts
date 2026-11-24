/// <reference types="node" />
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// nginx.conf allows the one inline script (theme before first paint) by hash instead of 'unsafe-inline'.
describe('production CSP', () => {
  it('pins the exact inline script of index.html', () => {
    const html = readFileSync('index.html', 'utf8')
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
    const conf = readFileSync('security-headers.conf', 'utf8')
    for (const script of scripts) {
      const hash = createHash('sha256').update(script).digest('base64')
      expect(conf).toContain(`'sha256-${hash}'`)
    }
    expect(conf).not.toContain("script-src 'self' 'unsafe-inline'")
  })

  it('every static location includes the security headers (nginx drops server-level add_header there)', () => {
    const conf = readFileSync('nginx.conf', 'utf8')
    const locations = [...conf.matchAll(/^\s*location ([^{\n]+)\{([^}]*)\}/gm)]
    for (const [, path, body] of locations) {
      if (path.trim() === '/api/') continue
      expect(body, path).toContain('include /etc/nginx/snippets/security-headers.conf;')
    }
    expect(locations.length).toBeGreaterThanOrEqual(4)
  })

  it('the access log never contains query strings (the SMS webhook token is one)', () => {
    const conf = readFileSync('nginx.conf', 'utf8')
    expect(conf).toMatch(/access_log \S+ fikso_noquery;/)
    const format = conf.slice(conf.indexOf('log_format fikso_noquery'), conf.indexOf(';', conf.indexOf('log_format fikso_noquery')))
    expect(format).not.toMatch(/\$request[ '"]|\$request_uri|\$args|\$query_string/)
  })
})
