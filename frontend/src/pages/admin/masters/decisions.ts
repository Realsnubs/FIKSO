import { t } from '../../../i18n/lv'
import type { DecisionAction, DecisionGroup, DecisionReason } from '../../../types/masters'
import { calendarDate } from '../../../i18n/format'

/**
 * Which decision buttons a status offers. UX only — it mirrors `master_admin.TRANSITIONS` so impossible
 * actions are not offered; the backend checks every decision again (INVALID_TRANSITION, VERSION_CONFLICT).
 */
export const ACTIONS: Record<'profile' | DecisionGroup, Record<string, DecisionAction[]>> = {
  profile: { pending_approval: ['approve', 'reject'], rejected: ['approve'] },
  specialisations: { requested: ['approve', 'reject'], approved: ['revoke'] },
  competencies: { declared: ['verify', 'reject'], verified: ['revoke'] },
  qualifications: { submitted: ['verify', 'reject'], verified: ['revoke'] },
}

/** The API's limit for one bulk preview or verification (schemas BULK_VERIFY_MAX); larger sets are split. */
export const BULK_VERIFY_MAX = 50

/** Rejections and revocations carry a reason (the backend requires it) and are confirmed separately. */
export function needsReason(action: DecisionAction): boolean {
  return action === 'reject' || action === 'revoke'
}

/** A backend reason in Latvian, with the qualification and date it names when it names one. */
export function decisionReasonText(reason: DecisionReason): string {
  const base = t.decisionReasons[reason.code] ?? reason.code
  const { name, valid_until: validUntil } = reason.details
  const named = typeof name === 'string' ? `${base}: ${name}` : base
  return typeof validUntil === 'string' ? `${named} (${t.masterCard.validUntil.toLowerCase()} ${calendarDate(validUntil)})` : named
}
