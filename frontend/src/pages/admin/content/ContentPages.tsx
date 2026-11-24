import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { catalogueApi } from '../../../api/endpoints'
import { adminWorkApi } from '../../../api/work'
import { AdminNav } from '../../../components/AdminNav'
import { Skeleton } from '../../../components/Skeleton'
import { StatusBadge } from '../../../components/StatusBadge'
import { rigaDateTime } from '../../../i18n/format'
import { t } from '../../../i18n/lv'
import { usePageTitle } from '../../../i18n/usePageTitle'
import type { ContentData, ContentPage, Lang3, PageTextData } from '../../../types/work'
import { useAction, useLoad } from '../../../work/hooks'
import { ErrorLine } from '../../../work/parts'

const tc = t.app.admin.content
const LANGS: Lang3[] = ['lv', 'en', 'ru']

export function ContentListPage() {
  usePageTitle(tc.title)
  const { data, error, loading } = useLoad(() => adminWorkApi.contentList())
  return (
    <section>
      <AdminNav />
      <h1>{tc.title}</h1>
      <ErrorLine message={error} />
      {loading && !data ? (
        <Skeleton variant="list" />
      ) : (
        <ul className="plain stack">
          {(data ?? []).map((item) => (
            <li key={item.specialisation_id} className="card item-row">
              <div>
                <strong>{item.specialisation_name}</strong>
                <div className="muted">
                  {item.category_name}
                  {item.slug && ` · /${item.slug}`}
                </div>
              </div>
              <span className="actions">
                {item.published ? <StatusBadge label={tc.published} tone="success" /> : <StatusBadge label={tc.empty} tone="neutral" />}
                {item.has_draft && <StatusBadge label={tc.draft} tone="info" />}
              </span>
              <Link to={`/admin/content/${item.specialisation_id}`} className="link-button button-small">
                {tc.edit}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const emptyText = (): PageTextData => ({ can_do: [], prepare: [], faq: [] })

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Drop empty strings so the backend stores only real texts (an empty translation means Latvian fallback). */
function clean(data: ContentData): ContentData {
  const locales: ContentData['locales'] = {}
  for (const lang of LANGS) {
    const text = data.locales[lang]
    if (!text) continue
    const out: PageTextData = { can_do: text.can_do, prepare: text.prepare, faq: text.faq.filter((f) => f.q.trim() && f.a.trim()) }
    for (const key of ['title', 'lead', 'seo_title', 'seo_description', 'name'] as const) {
      if (text[key]?.trim()) out[key] = text[key]!.trim()
    }
    locales[lang] = out
  }
  const services: ContentData['services'] = {}
  for (const [id, texts] of Object.entries(data.services)) {
    const kept = Object.fromEntries(Object.entries(texts).filter(([, v]) => v && v.trim()))
    if (Object.keys(kept).length) services[id] = kept
  }
  return { locales, card_image: data.card_image || null, gallery: data.gallery, services }
}

/** Editor of one specialisation page: three languages, images, versions; publishing is a separate step. */
export function ContentEditPage() {
  const { specId = '' } = useParams()
  usePageTitle(tc.title)
  const page = useLoad(() => adminWorkApi.content(specId), 0, [specId])
  const media = useLoad(() => adminWorkApi.media())
  const services = useLoad(async () => {
    const tree = await catalogueApi.tree()
    for (const c of tree.categories) {
      const spec = c.specialisations.find((s) => s.id === specId)
      if (spec) return spec.services.filter((s) => !['archived', 'rejected'].includes(s.status))
    }
    return []
  }, 0, [specId])
  const action = useAction()
  const [lang, setLang] = useState<Lang3>('lv')
  const [draft, setDraft] = useState<ContentData | null>(null)
  const [slug, setSlug] = useState<string | null>(null)

  const p = page.data
  if (page.loading && !p) return <Skeleton variant="page" />
  if (!p) return <ErrorLine message={page.error} />
  const source = p.draft?.data ?? p.published?.data
  const data: ContentData = draft ?? {
    locales: source?.locales ?? {},
    card_image: source?.card_image ?? null,
    gallery: source?.gallery ?? [],
    services: source?.services ?? {},
  }
  const text = { ...emptyText(), ...data.locales[lang] }
  const setText = (patch: Partial<PageTextData>) => setDraft({ ...data, locales: { ...data.locales, [lang]: { ...text, ...patch } } })
  const apply = (result: ContentPage | undefined) => {
    if (result) {
      page.setData(result)
      setDraft(null)
      setSlug(null)
    }
  }
  const ready = (media.data ?? []).filter((m) => m.status === 'ready' && !m.consent_withdrawn_at)

  return (
    <section>
      <AdminNav />
      <Link to="/admin/content" className="back-link">
        <span aria-hidden="true">←</span> {tc.title}
      </Link>
      <div className="page-head">
        <h1>{p.specialisation_name}</h1>
        <span className="actions">
          {p.published_version_no ? <StatusBadge label={`${tc.published} · ${tc.version(p.published_version_no)}`} tone="success" /> : null}
          {p.draft && <StatusBadge label={tc.draft} tone="info" />}
        </span>
      </div>
      <ErrorLine message={action.error} />

      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault()
          apply(await action.run(() => adminWorkApi.setSlug(specId, slug ?? p.slug, p.version)))
        }}
      >
        <label>
          {tc.slug}
          <input value={slug ?? p.slug} pattern="[a-z0-9]+(-[a-z0-9]+)*" onChange={(e) => setSlug(e.target.value)} />
        </label>
        <button type="submit" className="button-secondary button-small" disabled={action.busy || (slug ?? p.slug) === p.slug}>
          {tc.saveSlug}
        </button>
        {p.published_version_no && (
          <a href={`/pakalpojumi/${p.slug}`} target="_blank" rel="noreferrer">
            {tc.view}
          </a>
        )}
      </form>

      <div className="section-gap">
        <span className="lang-switch" role="group" aria-label={tc.language}>
          {LANGS.map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </button>
          ))}
        </span>
      </div>
      {lang !== 'lv' && <p className="hint">{tc.fallbackNote}</p>}

      <section className="card stack">
        {lang !== 'lv' && (
          <div className="field">
            <label htmlFor="ce-name">{tc.name}</label>
            <input id="ce-name" maxLength={120} value={text.name ?? ''} onChange={(e) => setText({ name: e.target.value })} />
          </div>
        )}
        <div className="field">
          <label htmlFor="ce-title">{tc.pageTitle}</label>
          <input id="ce-title" maxLength={120} value={text.title ?? ''} onChange={(e) => setText({ title: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ce-lead">{tc.lead}</label>
          <textarea id="ce-lead" rows={3} maxLength={600} value={text.lead ?? ''} onChange={(e) => setText({ lead: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ce-cando">{tc.canDo}</label>
          <textarea id="ce-cando" rows={4} value={text.can_do.join('\n')} onChange={(e) => setText({ can_do: lines(e.target.value) })} />
        </div>
        <div className="field">
          <label htmlFor="ce-prep">{tc.prepare}</label>
          <textarea id="ce-prep" rows={3} value={text.prepare.join('\n')} onChange={(e) => setText({ prepare: lines(e.target.value) })} />
        </div>
        <fieldset className="stack">
          <legend>{tc.faq}</legend>
          {text.faq.map((f, i) => (
            <div key={i} className="stack faq-edit">
              <input aria-label={tc.question} placeholder={tc.question} maxLength={300} value={f.q} onChange={(e) => setText({ faq: text.faq.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)) })} />
              <textarea aria-label={tc.answer} placeholder={tc.answer} rows={2} maxLength={600} value={f.a} onChange={(e) => setText({ faq: text.faq.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)) })} />
              <button type="button" className="button-ghost button-small" onClick={() => setText({ faq: text.faq.filter((_, j) => j !== i) })}>
                {t.app.masterOrder.remove}
              </button>
            </div>
          ))}
          <button type="button" className="button-secondary button-small" disabled={text.faq.length >= 30} onClick={() => setText({ faq: [...text.faq, { q: '', a: '' }] })}>
            {tc.addFaq}
          </button>
        </fieldset>
        <div className="field">
          <label htmlFor="ce-seot">{tc.seoTitle}</label>
          <input id="ce-seot" maxLength={120} value={text.seo_title ?? ''} onChange={(e) => setText({ seo_title: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ce-seod">{tc.seoDescription}</label>
          <textarea id="ce-seod" rows={2} maxLength={300} value={text.seo_description ?? ''} onChange={(e) => setText({ seo_description: e.target.value })} />
        </div>
      </section>

      <section className="card stack" aria-labelledby="ce-services">
        <h2 id="ce-services">{tc.services}</h2>
        {(services.data ?? []).map((s) => (
          <div key={s.id} className="field">
            <label htmlFor={`ce-s-${s.id}`}>
              <code>{s.w_id}</code> {s.name}
            </label>
            <textarea
              id={`ce-s-${s.id}`}
              rows={2}
              maxLength={600}
              value={data.services[s.id]?.[lang] ?? ''}
              onChange={(e) => setDraft({ ...data, services: { ...data.services, [s.id]: { ...data.services[s.id], [lang]: e.target.value } } })}
            />
          </div>
        ))}
      </section>

      <section className="card stack" aria-labelledby="ce-images">
        <h2 id="ce-images">{tc.cardImage}</h2>
        <select aria-label={tc.cardImage} value={data.card_image ?? ''} onChange={(e) => setDraft({ ...data, card_image: e.target.value || null })}>
          <option value="">{tc.noImage}</option>
          {ready.map((m) => (
            <option key={m.id} value={m.id}>
              {m.alt.lv || m.id.slice(0, 8)} · {m.width}×{m.height}
            </option>
          ))}
        </select>
        <h3>{tc.gallery}</h3>
        <ul className="media-grid plain">
          {ready.map((m) => {
            const inGallery = data.gallery.find((g) => g.media_id === m.id)
            return (
              <li key={m.id} className={inGallery ? 'selected' : undefined}>
                <img src={m.urls['560']} alt={m.alt.lv ?? ''} />
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={Boolean(inGallery)}
                    onChange={(e) =>
                      setDraft({
                        ...data,
                        gallery: e.target.checked ? [...data.gallery, { media_id: m.id, kind: 'after', caption: {} }] : data.gallery.filter((g) => g.media_id !== m.id),
                      })
                    }
                  />{' '}
                  {tc.add}
                </label>
              </li>
            )
          })}
        </ul>
      </section>

      <div className="actions sticky-actions">
        <button type="button" className="button-secondary" disabled={action.busy || !draft} onClick={async () => apply(await action.run(() => adminWorkApi.saveDraft(specId, clean(data), p.version)))}>
          {tc.saveDraft}
        </button>
        <button type="button" disabled={action.busy || Boolean(draft) || !p.draft} onClick={async () => apply(await action.run(() => adminWorkApi.publish(specId, p.version)))}>
          {tc.publish}
        </button>
        {p.published_version_no && (
          <button type="button" className="button-ghost" disabled={action.busy} onClick={async () => apply(await action.run(() => adminWorkApi.unpublish(specId, p.version)))}>
            {tc.unpublish}
          </button>
        )}
      </div>

      {p.history.length > 0 && (
        <section className="card stack" aria-labelledby="ce-history">
          <h2 id="ce-history">{tc.history}</h2>
          <ul className="plain stack">
            {p.history.map((v) => (
              <li key={v.id} className="item-row">
                <span>
                  {tc.version(v.version_no)} · {tc.state[v.state]} · {rigaDateTime(v.published_at ?? v.created_at)}
                </span>
                <button type="button" className="button-ghost button-small" disabled={action.busy} onClick={async () => apply(await action.run(() => adminWorkApi.restore(specId, v.id, p.version)))}>
                  {tc.restore}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}
