// Types of the Stage C/D API (public catalogue, requests, matching, orders, commission). Money is a decimal string.

export interface LocalizedApi {
  lv: string
  en?: string
  ru?: string
}

export interface PublicImageApi {
  urls: Record<'560' | '800' | '1300', string>
  width: number
  height: number
  alt: Partial<Record<'lv' | 'en' | 'ru', string>>
}

export interface PublicServiceApi {
  id: string
  w_id: string
  name: LocalizedApi
  description: Partial<Record<'lv' | 'en' | 'ru', string>> | null
}

export interface PublicSpecialisationApi {
  id: string
  slug: string
  name: LocalizedApi
  description: LocalizedApi | null
  lead: Partial<Record<'lv' | 'en' | 'ru', string>> | null
  status: 'active' | 'planned'
  services: PublicServiceApi[]
  card_image: PublicImageApi | null
}

export interface PublicCatalogueApi {
  computed_at: string
  categories: { id: string; name: LocalizedApi; specialisations: PublicSpecialisationApi[] }[]
}

export interface PageTextApi {
  title?: string
  lead?: string
  can_do?: string[]
  prepare?: string[]
  faq?: { q: string; a: string }[]
  seo_title?: string
  seo_description?: string
  name?: string
}

export interface SpecialisationPageApi extends PublicSpecialisationApi {
  category: { id: string; name: LocalizedApi }
  texts: Partial<Record<'lv' | 'en' | 'ru', PageTextApi>>
  gallery: (PublicImageApi & { kind: 'before' | 'after'; caption: Partial<Record<'lv' | 'en' | 'ru', string>> })[]
  terms: { hourly_rate_eur: string; minimum_order_eur: string; materials_note: LocalizedApi }
}

/** A city a master works in and a request is located in (data-driven list, GET /public/cities). */
export interface CityApi {
  code: string
  name: Record<'lv' | 'en' | 'ru', string>
}

/** A communication language between client and master — not an interface language (GET /public/communication-languages). */
export interface CommunicationLanguageApi {
  code: string
  name: Record<'lv' | 'en' | 'ru', string>
  native_name: string
  flag: string | null
}

/** `any` = the client accepts any available language. */
export type RequestLanguage = string

export interface PublicTerms {
  hourly_rate_eur: string
  minimum_order_eur: string
  materials_note: string
  materials_note_lang: 'lv' | 'en' | 'ru'
}

export type RequestStatus = 'draft' | 'matching' | 'proposed' | 'confirmed' | 'unserved' | 'cancelled'
export type OrderStatus =
  | 'offered'
  | 'declined'
  | 'expired'
  | 'accepted'
  | 'scheduled'
  | 'en_route'
  | 'in_progress'
  | 'completed'
  | 'reviewed'
  | 'cancelled'

export interface ProposalMaster {
  candidate_id: string
  role: 'proposal' | 'alternative'
  first_name: string
  description: string | null
  rating_avg: string | null
  rating_count: number
  completed_jobs: number
  eta_minutes: number
  distance_km: string
}

export interface OrderSummary {
  id: string
  status: OrderStatus
  master_name: string
  master_phone: string | null
  offered_at: string
  accepted_at: string | null
  en_route_at: string | null
  arrived_at: string | null
  work_started_at: string | null
  work_completed_at: string | null
  completed_at: string | null
  estimated_start: string
  scheduled_start: string | null
  scheduled_end: string | null
  master_location: { lat: number; lon: number } | null
  labour_amount_eur: string | null
  materials_amount_eur: string | null
  billable_minutes: number | null
  work_description: string | null
  review_rating: number | null
}

export interface ClientRequest {
  id: string
  status: RequestStatus
  unserved_reason: 'no_candidates' | 'rounds_exhausted' | null
  service: { id: string; w_id: string; name: string; specialisation: string; category: string }
  description: string
  request_type: 'immediate' | 'reserved'
  preferred_time_from: string | null
  preferred_time_to: string | null
  address: string
  flat: string | null
  access_info: string | null
  geocode_source: string
  source: string
  city: CityApi | null
  communication_language: RequestLanguage
  current_round: number
  photos: { id: string; size_bytes: number; uploaded_at: string }[]
  created_at: string
  submitted_at: string | null
  cancelled_at: string | null
  version: number
  proposal: { round: number; expires_at: string; masters: ProposalMaster[] } | null
  order: OrderSummary | null
}

export interface ClientRequestListItem {
  id: string
  status: RequestStatus
  w_id: string
  service_name: string
  created_at: string
  order_status: OrderStatus | null
}

export interface RequestCreatePayload {
  w_id: string
  description: string
  request_type: 'immediate' | 'reserved'
  preferred_time_from?: string
  preferred_time_to?: string
  address: string
  flat?: string
  access_info?: string
  lat?: string
  lon?: string
  city: string
  communication_language: RequestLanguage
  src?: string
}

export interface WorkProfile {
  approval_status: string
  availability_mode: 'available_now' | 'available_for_reservations' | 'unavailable'
  is_busy: boolean
  description: string | null
  work_city: string | null
  languages: string[]
  location_updated_at: string | null
  location_fresh: boolean
  location_interval_seconds: number
  rating_avg: string | null
  rating_count: number
  completed_jobs: number
  commission_balance_eur: string
  commission_limit_eur: string
  commission_limit_reached: boolean
}

export interface WorksheetData {
  state: 'draft' | 'finalised'
  work_description: string | null
  limitations_explained: string | null
  is_temporary_repair: boolean
  internal_notes: string | null
  materials: { name: string; quantity: string; unit: string | null; amount_eur: string }[]
  materials_amount_eur: string
  external_costs_eur: string
  billable_seconds: number | null
  travel_minutes: number | null
  labour_amount_eur: string | null
  commission_eur: string | null
}

export interface MasterOrder {
  id: string
  status: OrderStatus
  order_type: 'immediate' | 'reserved'
  service: { id: string; w_id: string; name: string; specialisation: string; category: string }
  description: string
  photos: { id: string; size_bytes: number; uploaded_at: string }[]
  estimated_start: string
  scheduled_start: string | null
  scheduled_end: string | null
  offer_expires_at: string | null
  city: CityApi | null
  communication_language: RequestLanguage
  client: { name: string; phone: string | null } | null
  address: { address: string; flat: string | null; access_info: string | null; lat: number; lon: number } | null
  timeline: Record<
    'offered_at' | 'accepted_at' | 'en_route_at' | 'arrived_at' | 'work_started_at' | 'work_completed_at' | 'completed_at',
    string | null
  >
  work_running: boolean
  billable_seconds: number
  terms: { hourly_rate_eur: string; minimum_order_eur: string; commission_rate: string }
  worksheet: WorksheetData | null
}

export interface LedgerEntry {
  id: string
  type: 'charge' | 'payment' | 'adjustment'
  order_id: string | null
  base_labour_eur: string | null
  amount_eur: string
  payment_method: 'cash' | 'bank_transfer' | null
  paid_on: string | null
  comment: string | null
  created_at: string
  reference?: string | null
  rate?: string | null
}

export interface MasterCommission {
  charged_total_eur: string
  paid_total_eur: string
  adjustments_total_eur: string
  balance_eur: string
  amount_due_eur: string
  limit_eur: string
  limit_reached: boolean
  entries: LedgerEntry[]
}

export interface AdminCommissionRow {
  master_id: string
  name: string
  email: string
  balance_eur: string
  limit_eur: string
  limit_reached: boolean
}

export interface AdminCommissionDetail {
  master_id: string
  name: string
  charged_total_eur: string
  paid_total_eur: string
  adjustments_total_eur: string
  balance_eur: string
  limit_eur: string
  limit_reached: boolean
  entries: LedgerEntry[]
}

export interface MediaItem {
  id: string
  width: number
  height: number
  urls: Record<'560' | '800' | '1300', string>
  alt: Partial<Record<'lv' | 'en' | 'ru', string>>
  status: 'ready' | 'archived'
  rights_basis: 'own' | 'client_consent' | 'licence'
  rights_reference: string | null
  consent_given_on: string | null
  consent_withdrawn_at: string | null
  created_at: string
}

export type Lang3 = 'lv' | 'en' | 'ru'

export interface PageTextData {
  title?: string
  lead?: string
  can_do: string[]
  prepare: string[]
  faq: { q: string; a: string }[]
  seo_title?: string
  seo_description?: string
  name?: string
}

export interface ContentData {
  locales: Partial<Record<Lang3, PageTextData>>
  card_image?: string | null
  gallery: { media_id: string; kind: 'before' | 'after'; caption: Partial<Record<Lang3, string>> }[]
  services: Record<string, Partial<Record<Lang3, string>>>
}

export interface ContentVersion {
  id: string
  version_no: number
  state: 'draft' | 'published' | 'superseded'
  data: ContentData
  created_at: string
  updated_at: string | null
  published_at: string | null
}

export interface ContentPage {
  id: string
  specialisation_id: string
  specialisation_name: string
  slug: string
  version: number
  published_version_no: number | null
  draft: ContentVersion | null
  published: ContentVersion | null
  history: ContentVersion[]
}

export interface ContentListItem {
  specialisation_id: string
  specialisation_name: string
  category_name: string
  status: string
  content_id: string | null
  slug: string | null
  has_draft: boolean
  published: boolean
}

export interface CommercialTermsRow {
  id: string
  hourly_rate_eur: string
  minimum_order_eur: string
  materials_note: LocalizedApi
  effective_from: string
  reason: string | null
  created_at: string
}

export interface AdminRequestRow {
  id: string
  status: RequestStatus
  w_id: string
  service_name: string
  request_type: 'immediate' | 'reserved'
  source: string
  round: number
  created_at: string
  order_status: OrderStatus | null
  unserved_reason: string | null
  city: string | null
  communication_language: RequestLanguage
}

export interface AdminRequestDetail extends ClientRequest {
  address: string
  rounds: {
    run_no: number
    attempt: number
    outcome: string
    eligible: number
    available: number
    excluded: Record<string, number>
    close_reason: string | null
    created_at: string
    closed_at: string | null
    candidates: { rank: number; master: string; eta_minutes: number; eta_source: string; distance_km: string; role: string; chosen: boolean }[]
  }[]
  history: { entity: string; from: string | null; to: string; actor_type: string; reason: string | null; at: string }[]
}

export interface AdminMasterWork {
  work_city: CityApi | null
  languages: string[]
  availability_mode: WorkProfile['availability_mode']
  is_busy: boolean
  location_fresh: boolean
  ready_for_matching: boolean
}

export interface StatsOverview {
  period_days: number
  queue: { masters_pending: number; specialisations_requested: number; qualifications_submitted: number }
  users: Record<string, number>
  masters: Record<string, number>
  masters_by_mode: Record<string, number>
  catalogue: { services_by_status: Record<string, number>; orderable_services: number }
  public: Record<string, number>
  requests: { by_status: Record<string, number>; by_source: Record<string, number> }
  matching: { outcomes: Record<string, number>; round_endings: Record<string, number> }
  orders: Record<string, number>
  commission: { charged_eur: string; paid_eur: string; outstanding_eur: string }
  worker: { last_finished_at: string | null; stuck_runs: number }
}

export interface AppNotification {
  id: string
  type: string
  payload: Record<string, string>
  created_at: string
  read: boolean
}
