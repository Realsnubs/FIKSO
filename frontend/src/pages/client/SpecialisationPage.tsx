import { Link, useParams } from 'react-router'
import { Skeleton } from '../../components/Skeleton'
import {
  availableSpecialisations,
  findSpecialisation,
  localized,
  orderLink,
  orderableServices,
  usePublicCatalogue,
  useSpecialisationContent,
} from '../../catalogue/publicCatalogue'
import { useEffect } from 'react'
import { publicApi } from '../../api/work'
import { sentence } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { useLanguage } from '../../i18n/LanguageContext'
import { usePageTitle } from '../../i18n/usePageTitle'
import { DemoBanner, OrderLink, PriceCard, PriceLine, SpecialisationCard } from './parts'

const ts = t.shop

const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

/**
 * One page per specialisation (owner decision 2026-11-04), its concrete services (W-IDs) inside. Sections appear only
 * when the content has them; nothing is filled in. Open to guests; ordering asks for sign-in and keeps the W-ID.
 */
export function SpecialisationPage() {
  const { id = '' } = useParams()
  const { language } = useLanguage()
  const { catalogue, loading } = usePublicCatalogue()
  const found = catalogue ? findSpecialisation(catalogue, id) : null
  const name = found ? localized(found.spec.name, language) : null
  usePageTitle(name ?? t.header.services)
  const pageContent = useSpecialisationContent(id, Boolean(found && catalogue && !catalogue.demo))
  const backendId = found?.spec.backendId
  useEffect(() => {
    if (backendId) publicApi.event('specialisation_view', backendId).catch(() => undefined)
  }, [backendId])

  if (loading) return <Skeleton variant="page" />
  if (!found) {
    return (
      <section className="notfound">
        <h1>{ts.notFound}</h1>
        <Link to="/pakalpojumi" className="back-link">
          <span aria-hidden="true">←</span> {ts.back}
        </Link>
      </section>
    )
  }

  const { spec, category } = found
  const content = pageContent ?? spec.content
  const orderable = orderableServices(spec)
  const text = (value: { lv: string; en?: string; ru?: string }) => localized(value, language)
  // One orderable service: the page CTA orders it directly; several: the CTA leads to the choice.
  const primaryOrder = orderable.length === 1 ? orderLink(orderable[0].wId) : orderable.length > 1 ? '#izvele' : undefined
  const others = availableSpecialisations(category)
    .filter((s) => s.id !== spec.id)
    .slice(0, 3)

  return (
    <section>
      {catalogue?.demo && <DemoBanner />}
      <Link to="/pakalpojumi" className="back-link">
        <span aria-hidden="true">←</span> {ts.back}
      </Link>
      <div className="svc-page">
        <div className="main">
          <header>
            <p className="eyebrow">
              {text(category.name)} · {name}
            </p>
            <h1>{content?.title ? text(content.title) : name}</h1>
            {(content?.lead || spec.description) && (
              <p className="lead">{content?.lead ? text(content.lead) : sentence(text(spec.description!))}</p>
            )}
            {orderable.length > 0 && <PriceLine />}
            {spec.status === 'planned' && <p className="notice">{ts.planned}</p>}
          </header>

          {spec.services.length > 0 && (
            <section className="svc-section" id="izvele" aria-labelledby="sp-choose">
              <h2 id="sp-choose">{ts.choose}</h2>
              <ul className="options">
                {spec.services.map((service) => (
                  <li key={service.id} className={service.orderable && spec.status === 'active' ? 'option' : 'option off'}>
                    <strong>
                      <code>{service.wId}</code> {text(service.name)}
                    </strong>
                    {service.orderable && spec.status === 'active' ? (
                      <Link to={orderLink(service.wId)} className="link-button" aria-label={`${ts.order}: ${service.wId} ${text(service.name)}`}>
                        {ts.order}
                      </Link>
                    ) : (
                      <span className="not-orderable">{ts.notOrderable}</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {content?.canDo && content.canDo.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-cando">
              <h2 id="sp-cando">{ts.canDo}</h2>
              <div className="check-list">
                {content.canDo.map((item, i) => (
                  <div key={i} className="check-row">
                    {CHECK}
                    <span>{text(item)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {content?.prepare && content.prepare.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-prepare">
              <h2 id="sp-prepare">{ts.prepare}</h2>
              {content.prepare.map((item, i) => (
                <p key={i}>{text(item)}</p>
              ))}
            </section>
          )}

          {content?.photos && content.photos.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-works">
              <h2 id="sp-works">{ts.works}</h2>
              <div className="gallery">
                {content.photos.map((photo) => (
                  <figure key={photo.src}>
                    <div className="ph">
                      <img src={photo.src} alt={text(photo.alt)} loading="lazy" />
                      <span className="tag-photo">{photo.kind === 'before' ? ts.before : ts.after}</span>
                    </div>
                    <figcaption>{text(photo.caption)}</figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}

          {orderable.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-how">
              <h2 id="sp-how">{ts.howTitle}</h2>
              <ol className="steps">
                {(
                  [
                    [ts.step1, ts.step1Text],
                    [ts.step2, ts.step2Text],
                    [ts.step3, ts.step3Text],
                    [ts.step4, ts.step4Text],
                  ] as const
                ).map(([title, body], i) => (
                  <li key={title}>
                    <div className="step-chip" aria-hidden="true">
                      {String(i + 1).padStart(2, '0')}
                    </div>
                    <h3>{title}</h3>
                    <p>{body}</p>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {content?.faq && content.faq.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-faq">
              <h2 id="sp-faq">{ts.faq}</h2>
              <div className="faq">
                {content.faq.map((item, i) => (
                  <details key={i}>
                    <summary>{text(item.question)}</summary>
                    <p>{text(item.answer)}</p>
                  </details>
                ))}
              </div>
            </section>
          )}

          {primaryOrder && (
            <section className="cta-panel" aria-labelledby="sp-cta">
              <h2 id="sp-cta">{name}</h2>
              <p>{ts.ctaText}</p>
              <div className="actions">
                <OrderLink to={primaryOrder} className="link-button" />
              </div>
            </section>
          )}

          {others.length > 0 && (
            <section className="svc-section" aria-labelledby="sp-others">
              <h2 id="sp-others">{ts.others}</h2>
              <ul className="svc-grid">
                {others.map((s) => (
                  <SpecialisationCard key={s.id} spec={s} category={category} />
                ))}
              </ul>
            </section>
          )}
        </div>
        <aside className="svc-aside">
          <PriceCard orderTo={primaryOrder} />
        </aside>
      </div>
      {primaryOrder && (
        <>
          {/* Phones: the order link stays in reach; the spacer keeps the page end visible above the bar. */}
          <div className="mobile-bar-spacer" aria-hidden="true" />
          <div className="mobile-bar">
            <OrderLink to={primaryOrder} className="link-button" />
          </div>
        </>
      )}
    </section>
  )
}
