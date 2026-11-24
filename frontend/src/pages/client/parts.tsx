import { Link } from 'react-router'
import { localized, orderableServices, usePublicTerms } from '../../catalogue/publicCatalogue'
import { COMMERCIAL } from '../../commercial'
import { sentence } from '../../i18n/format'
import { t } from '../../i18n/lv'
import { useLanguage } from '../../i18n/LanguageContext'
import type { PublicCategory, PublicSpecialisation } from '../../types/publicCatalogue'

const ts = t.shop

const TOOL = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />
  </svg>
)

/** A specialisation in the catalogue: the whole card is a link to its page (navigation, not an action). */
export function SpecialisationCard({ spec, category }: { spec: PublicSpecialisation; category: PublicCategory }) {
  const { language } = useLanguage()
  const image = spec.content?.cardImage
  const count = orderableServices(spec).length
  return (
    <li>
      <Link to={`/pakalpojumi/${spec.id}`} className="svc-card">
        {image ? (
          <div className="svc-media">
            <img src={image.src} alt={localized(image.alt, language)} loading="lazy" />
            <span className="tag-photo">{ts.after}</span>
          </div>
        ) : (
          <div className="svc-media icon">{TOOL}</div>
        )}
        <div className="svc-body">
          <p className="eyebrow">{localized(category.name, language)}</p>
          <h3>{localized(spec.name, language)}</h3>
          {spec.description && <p>{sentence(localized(spec.description, language))}</p>}
          <div className="svc-meta">
            <span>{ts.services(count)}</span>
            <span>{t.commercial.rate(COMMERCIAL.hourlyRate)}</span>
          </div>
          <span className="svc-more">
            {ts.more} <span aria-hidden="true">→</span>
          </span>
        </div>
      </Link>
    </li>
  )
}

/** The confirmed commercial terms (one source: src/commercial.ts), optionally with the order link. */
export function PriceCard({ orderTo }: { orderTo?: string }) {
  const { language } = useLanguage()
  const terms = usePublicTerms(language)
  // The live terms come from the API (admin-managed, C1); the confirmed values are the fallback.
  const rate = terms ? Number(terms.hourly_rate_eur) : COMMERCIAL.hourlyRate
  const minimum = terms ? Number(terms.minimum_order_eur) : COMMERCIAL.minimumOrder
  return (
    <div className="price-card">
      <p className="eyebrow">{ts.priceTitle}</p>
      <div className="price-amount">{t.commercial.rate(rate)}</div>
      <p className="hint">{t.commercial.rateNote}</p>
      <p className="min">{t.commercial.minimum(minimum)}</p>
      <p className="hint">{t.commercial.minimumNote}</p>
      <p className="hint" lang={terms?.materials_note_lang}>{terms?.materials_note ?? t.commercial.materials}</p>
      {orderTo && <OrderLink to={orderTo} className="link-button block" />}
    </div>
  )
}

export function DemoBanner() {
  return (
    <p className="demo-banner" role="note">
      {ts.demoBanner}
    </p>
  )
}

/** The order link: an in-page anchor (#izvele, to choose among several services) or the order route. */
export function OrderLink({ to, className, label }: { to: string; className: string; label?: string }) {
  if (to.startsWith('#')) {
    return (
      <a href={to} className={className}>
        {label ?? ts.order}
      </a>
    )
  }
  return (
    <Link to={to} className={className}>
      {label ?? ts.order}
    </Link>
  )
}

/** The price in one line, for the page header on phones (the full card follows the content there). */
export function PriceLine() {
  return (
    <p className="price-inline">
      <strong>{t.commercial.rate(COMMERCIAL.hourlyRate)}</strong> · {t.commercial.minimum(COMMERCIAL.minimumOrder)}
    </p>
  )
}
