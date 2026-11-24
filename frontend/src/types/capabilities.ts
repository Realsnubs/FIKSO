// Mirrors backend app/schemas/master.py (GET /master/capabilities, GET /master/catalogue and the master's
// application routes). Verifier instructions, storage keys and other masters' data are never part of it.
import type { MasterApprovalStatus } from './api'
import type {
  Attachment,
  CompetencyStatus,
  DecisionReason,
  SpecialisationStatus,
  SubmissionStatus,
} from './masters'

export interface SpecialisationApplication {
  specialisation_id: string
  name: string
  status: SpecialisationStatus
  requested_at: string
  decided_at: string | null
  decision_reason: string | null
}

export interface Competency {
  service_id: string
  w_id: string
  name: string
  specialisation_id: string
  status: CompetencyStatus
  declared_at: string
  decided_at: string | null
  decision_reason: string | null
  /** Whether the master can receive orders for this service now; `reasons` says why not (R-MST-12). */
  eligible: boolean
  reasons: DecisionReason[]
}

export interface Submission {
  id: string
  qualification_id: string
  qualification_name: string
  status: SubmissionStatus
  document_number: string | null
  /** An inclusive calendar date (YYYY-MM-DD). */
  valid_until: string | null
  submitted_at: string
  decided_at: string | null
  decision_reason: string | null
  expired: boolean
  expires_soon: boolean
  files: Attachment[]
}

export interface Capabilities {
  approval_status: MasterApprovalStatus
  /** The reason of the profile rejection, only while the profile is rejected. */
  rejection_reason: string | null
  /** The Riga business date (YYYY-MM-DD). */
  today: string
  specialisations: SpecialisationApplication[]
  competencies: Competency[]
  /** Every submission, newest first per qualification: the full history. */
  qualifications: Submission[]
}

export interface QualificationType {
  id: string
  name: string
  description: string | null
  status: string
  requires_document: boolean
  requires_document_number: boolean
  requires_expiry_date: boolean
  max_validity_months: number | null
}

export interface MasterCatalogueService {
  id: string
  w_id: string
  name: string
  status: string
  qualification_required: boolean
  qualification_ids: string[]
}

export interface MasterCatalogueSpecialisation {
  id: string
  category_id: string
  name: string
  description: string | null
  status: 'active' | 'planned'
  qualification_required: boolean
  qualification_ids: string[]
  services: MasterCatalogueService[]
}

/** What a master may apply for: requestable specialisations, declarable services, active qualification types. */
export interface MasterCatalogue {
  specialisations: MasterCatalogueSpecialisation[]
  qualification_types: QualificationType[]
}

export interface SubmissionForm {
  qualificationId: string
  documentNumber: string
  /** YYYY-MM-DD or empty. */
  validUntil: string
  files: File[]
}
