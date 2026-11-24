type Tone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

/** Presentation only: how a backend status looks. The statuses and their meaning come from the API. */
const TONES: Record<string, Tone> = {
  approved: 'success',
  verified: 'success',
  active: 'success',
  requested: 'info',
  declared: 'info',
  submitted: 'info',
  pending_approval: 'info',
  rejected: 'danger',
  revoked: 'danger',
  blocked: 'danger',
  withdrawn: 'neutral',
}

export function StatusBadge({ status, label, tone }: { status?: string; label: string; tone?: Tone }) {
  return <span className={`badge badge-${tone ?? (status ? (TONES[status] ?? 'neutral') : 'neutral')}`}>{label}</span>
}
