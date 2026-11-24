// Mirrors backend app/schemas/catalogue.py (Admin catalogue API, ARCHITECTURE §6a).

export type GroupStatus = 'active' | 'inactive' | 'planned' | 'archived'
export type ServiceStatus = 'draft' | 'active' | 'inactive' | 'planned' | 'hold' | 'rejected' | 'archived'
export type QualificationStatus = 'draft' | 'active' | 'archived'
export type CatalogueRole = 'issuer' | 'receiver' | 'isolated'
export type EntryKind = 'categories' | 'specialisations' | 'services' | 'qualifications'

interface Entry {
  id: string
  name: string
  description: string | null
  status_reason: string | null
  sort_order: number
  source: string
  source_ref: string | null
  version: number
  updated_at: string
}

export interface Qualification {
  id: string
  name: string
  description: string | null
  status: QualificationStatus
  requires_document: boolean
  requires_document_number: boolean
  requires_expiry_date: boolean
  max_validity_months: number | null
  verifier_instructions: string | null
  version: number
  updated_at: string
}

export interface Service extends Entry {
  specialisation_id: string
  w_id: string
  status: ServiceStatus
  risk_level: 'normal' | 'high'
  qualification_required: boolean
  restrictions: string | null
  review_note: string | null
  qualification_ids: string[]
  qualifications_ready: boolean
}

export interface Specialisation extends Entry {
  category_id: string
  status: GroupStatus
  qualification_required: boolean
  qualification_ids: string[]
  services: Service[]
}

export interface Category extends Entry {
  status: GroupStatus
  specialisations: Specialisation[]
}

/** Why a service cannot be ordered now (backend `catalogue.availability`, R-CAT-03). */
export interface AvailabilityReason {
  code: string
  details: Record<string, unknown>
}

/** A service as listed in the admin tree: the entry plus its availability, computed by the backend. */
export interface TreeService extends Service {
  eligible_masters: number
  orderable: boolean
  orderable_reasons: AvailabilityReason[]
}

export interface TreeSpecialisation extends Omit<Specialisation, 'services'> {
  services: TreeService[]
}

export interface TreeCategory extends Omit<Category, 'specialisations'> {
  specialisations: TreeSpecialisation[]
}

export interface CatalogueTree {
  catalogue_role: CatalogueRole
  can_create: boolean
  categories: TreeCategory[]
  qualifications: Qualification[]
}

export interface PlanEntry {
  kind: string
  id: string
  name: string
  w_id: string | null
  changes?: string[]
  locally_edited?: boolean
  reason?: string
}

export interface SyncImport {
  id: string
  status: 'previewed' | 'applied' | 'rejected'
  source_environment: string
  exported_at: string
  package_sha256: string
  preview: {
    create: PlanEntry[]
    update: PlanEntry[]
    unchanged: PlanEntry[]
    conflicts: PlanEntry[]
    links_to_add: number
  }
  created_at: string
  applied_at: string | null
}

// --- impact preview (R-CAT-18; backend app/schemas/catalogue.py ImpactIn / ImpactOut) -------------------------

/** One catalogue row the preview depended on, with its version (`BasisItemOut` / `BasisItemIn`). */
export interface BasisItem {
  kind: 'category' | 'specialisation' | 'service' | 'qualification'
  id: string
  version: number
}

export interface ImpactStatus {
  kind: 'status'
  status: string
  /** 3–500 characters when sent; the response echoes it, `null` when none was sent. */
  reason?: string | null
}

export interface ImpactMove {
  kind: 'move'
  /** The new category (specialisation) or specialisation (service). */
  target_id: string
}

export interface ImpactQualificationRequired {
  kind: 'qualification_required'
  value: boolean
}

export interface ImpactRequirements {
  kind: 'requirements'
  /** The new set of qualification types (≤ 2000). */
  qualification_ids: string[]
}

export interface ImpactActivateHold {
  kind: 'activate_hold'
  /** 3–500 characters. */
  reason: string
}

export type ImpactChange =
  | ImpactStatus
  | ImpactMove
  | ImpactQualificationRequired
  | ImpactRequirements
  | ImpactActivateHold

/** The entity / change combinations the backend previews (others: 422 IMPACT_CHANGE_NOT_SUPPORTED). */
export type ImpactRequest =
  | { entity: 'category'; id: string; change: ImpactStatus }
  | { entity: 'specialisation'; id: string; change: Exclude<ImpactChange, ImpactActivateHold> }
  | { entity: 'service'; id: string; change: ImpactChange }

export interface ServiceState {
  orderable: boolean
  eligible_masters: number
  reasons: AvailabilityReason[]
}

export interface ImpactService {
  service_id: string
  w_id: string
  name: string
  before: ServiceState
  after: ServiceState
}

/** Identification only: the preview never returns contact data. */
export interface MasterRef {
  master_id: string
  full_name: string
}

export interface ImpactMasters {
  by_specialisation_status: Record<string, number>
  by_competency_status: Record<string, number>
  /** At most 100 items, ordered by name; `total` counts all. */
  losing_eligibility: { total: number; items: MasterRef[] }
}

export interface ImpactResponse {
  entity: 'category' | 'specialisation' | 'service'
  id: string
  change: ImpactChange
  /** Send back as `expected_basis` when confirming the change. */
  basis: BasisItem[]
  services: ImpactService[]
  stops_being_orderable: string[]
  becomes_orderable: string[]
  masters: ImpactMasters
  /** Always `null` until client requests exist (step 5); see `notes.open_requests`. */
  open_requests: null
  notes: { open_requests: string; eligible_masters: string }
  /** ISO timestamp; master counts are a snapshot at this time. */
  computed_at: string
}
