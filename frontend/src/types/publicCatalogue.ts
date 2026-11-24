// The public catalogue as the client pages need it, mapped from GET /public/catalogue (or the isolated demo layer).

/** Content text per language. Latvian is the source; EN/RU exist only once translated (never auto-translated). */
export interface Localized {
  lv: string
  en?: string
  ru?: string
}

export interface PublicService {
  id: string
  wId: string
  name: Localized
  /** Decided by the backend (catalogue.availability): active and with an eligible service professional. */
  orderable: boolean
  /** Short service description from the page content (optional). */
  description?: Localized
}

export interface WorkPhoto {
  src: string
  alt: Localized
  caption: Localized
  kind: 'before' | 'after'
}

export interface FaqItem {
  question: Localized
  answer: Localized
}

/** Page content of a specialisation; every part is optional and a missing part is simply not shown. */
export interface SpecialisationContent {
  title?: Localized
  lead?: Localized
  canDo?: Localized[]
  prepare?: Localized[]
  photos?: WorkPhoto[]
  faq?: FaqItem[]
  cardImage?: { src: string; alt: Localized }
}

export interface PublicSpecialisation {
  id: string
  categoryId: string
  name: Localized
  description: Localized | null
  status: 'active' | 'planned'
  services: PublicService[]
  content: SpecialisationContent | null
  /** Backend UUID when `id` is the page slug (API mode). */
  backendId?: string
}

export interface PublicCategory {
  id: string
  name: Localized
  specialisations: PublicSpecialisation[]
}

export interface PublicCatalogue {
  /** True for the demo layer: the pages show a "Demonstrācija" banner and never send anything. */
  demo: boolean
  categories: PublicCategory[]
}
