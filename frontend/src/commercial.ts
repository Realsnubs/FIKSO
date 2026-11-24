/**
 * FIKSO commercial terms (owner, 2026-11-04): 40 € per hour of a service professional's work; the minimum order
 * value is 40 € — the lowest value of an order, not an extra charge. The one place the figures live in the
 * frontend: every page formats them through `t.commercial`. Planned: an admin-managed backend setting (stage C).
 */
export const COMMERCIAL = {
  hourlyRate: 40,
  minimumOrder: 40,
} as const
