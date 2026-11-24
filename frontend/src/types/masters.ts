// Mirrors backend app/schemas/admin_masters.py (GET /admin/masters, GET /admin/review-queue).
import type { MasterApprovalStatus, UserStatus } from './api'

export interface PendingCounts {
  specialisations: number
  competencies: number
  qualifications: number
}

export interface AdminMasterListItem {
  id: string
  user_id: string
  full_name: string
  email: string
  phone: string | null
  user_status: UserStatus
  approval_status: MasterApprovalStatus
  decided_at: string | null
  version: number
  registered_at: string
  pending: PendingCounts
}

export type QueueKind = 'specialisation' | 'competency' | 'qualification'

export interface ReviewQueueItem {
  kind: QueueKind
  master_id: string
  master_name: string
  approval_status: MasterApprovalStatus
  user_status: UserStatus
  item_id: string
  name: string
  /** Services (competencies) only. */
  w_id: string | null
  /** Qualification submissions only; an inclusive calendar date (YYYY-MM-DD). */
  valid_until: string | null
  since: string
  version: number
}

// GET /admin/masters/{id} (AdminMasterOut) and the decision routes, which answer with the same card.

/** A backend reason: an eligibility condition or a verification blocker (services/eligibility.py). */
export interface DecisionReason {
  code: string
  details: Record<string, unknown>
}

export type SpecialisationStatus = 'requested' | 'approved' | 'rejected' | 'revoked' | 'withdrawn'
export type CompetencyStatus = 'declared' | 'verified' | 'rejected' | 'revoked' | 'withdrawn'
export type SubmissionStatus = 'submitted' | 'verified' | 'rejected' | 'revoked' | 'withdrawn'

export interface AdminSpecialisation {
  specialisation_id: string
  name: string
  status: SpecialisationStatus
  requested_at: string
  decided_at: string | null
  decided_by: string | null
  decision_reason: string | null
  version: number
}

export interface AdminCompetency {
  service_id: string
  w_id: string
  name: string
  specialisation_id: string
  status: CompetencyStatus
  declared_at: string
  decided_at: string | null
  decided_by: string | null
  decision_reason: string | null
  version: number
  /** Whether the master can receive this service now; `reasons` says why not (R-MST-11). */
  eligible: boolean
  reasons: DecisionReason[]
}

export interface Attachment {
  id: string
  mime_type: string
  size_bytes: number
  uploaded_at: string
}

export interface AdminSubmission {
  id: string
  qualification_id: string
  qualification_name: string
  status: SubmissionStatus
  document_number: string | null
  /** An inclusive calendar date (YYYY-MM-DD). */
  valid_until: string | null
  submitted_at: string
  decided_at: string | null
  decided_by: string | null
  decision_reason: string | null
  version: number
  expired: boolean
  expires_soon: boolean
  files: Attachment[]
}

export interface QualificationRule {
  id: string
  name: string
  description: string | null
  status: string
  requires_document: boolean
  requires_document_number: boolean
  requires_expiry_date: boolean
  max_validity_months: number | null
  verifier_instructions: string | null
}

export interface AdminMaster {
  id: string
  user_id: string
  full_name: string
  email: string
  phone: string | null
  user_status: UserStatus
  blocked_reason: string | null
  approval_status: MasterApprovalStatus
  decided_by: string | null
  decided_at: string | null
  decision_reason: string | null
  version: number
  registered_at: string
  /** The Riga business date the expiry flags were computed for (YYYY-MM-DD). */
  today: string
  specialisations: AdminSpecialisation[]
  competencies: AdminCompetency[]
  qualifications: AdminSubmission[]
  qualification_types: QualificationRule[]
}

/** The decision groups of the card and their route segment (`/admin/masters/{id}/{segment}/{key}/{action}`). */
export type DecisionGroup = 'specialisations' | 'competencies' | 'qualifications'
export type DecisionAction = 'approve' | 'verify' | 'reject' | 'revoke'

// Bulk competency verification (POST …/competencies/bulk-verify/preview and …/bulk-verify, step 4.4.8).

export interface BulkPreviewItem {
  service_id: string
  /** null when the master has no such competency (COMPETENCY_NOT_FOUND). */
  w_id: string | null
  name: string | null
  status: CompetencyStatus | null
  /** The version a bulk verification of this item must carry. */
  expected_version: number | null
  verifiable: boolean
  reasons: DecisionReason[]
}

export interface BulkPreview {
  items: BulkPreviewItem[]
  /** True only when every item is verifiable: the backend applies all or nothing. */
  applicable: boolean
}

/** `details.items` of 409 BULK_VERIFY_REJECTED: every item that failed; nothing was verified. */
export interface BulkRejectedItem {
  service_id: string
  reasons: DecisionReason[]
}
