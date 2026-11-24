import type {
  AdminUser,
  GuestPayload,
  MasterApprovalStatus,
  Page,
  RegisterPayload,
  Role,
  TokenResponse,
  User,
  UserStatus,
} from '../types/api'
import type {
  BasisItem,
  CatalogueTree,
  EntryKind,
  ImpactRequest,
  ImpactResponse,
  Service,
  SyncImport,
} from '../types/catalogue'
import type {
  Capabilities,
  MasterCatalogue,
  SpecialisationApplication,
  Submission,
  SubmissionForm,
} from '../types/capabilities'
import type {
  AdminMaster,
  AdminMasterListItem,
  BulkPreview,
  DecisionAction,
  DecisionGroup,
  QueueKind,
  ReviewQueueItem,
} from '../types/masters'
import { apiBlob, apiRequest } from './client'

export const authApi = {
  login: (email: string, password: string) =>
    apiRequest<TokenResponse>('/auth/login', { method: 'POST', body: { email, password } }),
  register: (role: 'client' | 'master', data: RegisterPayload) =>
    apiRequest<TokenResponse>(`/auth/register/${role}`, { method: 'POST', body: data }),
  logout: () => apiRequest<void>('/auth/logout', { method: 'POST' }),
  guest: (data: GuestPayload) => apiRequest<TokenResponse>('/auth/guest/client', { method: 'POST', body: data }),
  requestSmsCode: (phone: string) => apiRequest<void>('/auth/sms-code', { method: 'POST', body: { phone } }),
  verifySmsCode: (phone: string, code: string) =>
    apiRequest<TokenResponse>('/auth/sms-code/verify', { method: 'POST', body: { phone, code } }),
  setPassword: (password: string, currentPassword?: string) =>
    apiRequest<User>('/me/password', { method: 'POST', body: { password, current_password: currentPassword } }),
  me: () => apiRequest<User>('/me'),
}

export interface UserFilters {
  role?: Role
  status?: UserStatus
  cursor?: string | null
}

export const adminApi = {
  listUsers: ({ role, status, cursor }: UserFilters) => {
    const params = new URLSearchParams({ limit: '25' })
    if (role) params.set('role', role)
    if (status) params.set('status', status)
    if (cursor) params.set('cursor', cursor)
    return apiRequest<Page<AdminUser>>(`/admin/users?${params.toString()}`)
  },
  blockUser: (id: string, reason: string) =>
    apiRequest<AdminUser>(`/admin/users/${id}/block`, { method: 'POST', body: { reason } }),
  unblockUser: (id: string) => apiRequest<AdminUser>(`/admin/users/${id}/unblock`, { method: 'POST' }),
}

/** The master's own capabilities (ARCHITECTURE §6b): the API knows the master from the session, never by ID. */
export const masterApi = {
  capabilities: () => apiRequest<Capabilities>('/master/capabilities'),
  catalogue: () => apiRequest<MasterCatalogue>('/master/catalogue'),
  requestSpecialisation: (specialisationId: string) =>
    apiRequest<SpecialisationApplication>('/master/specialisations', {
      method: 'POST',
      body: { specialisation_id: specialisationId },
    }),
  withdrawSpecialisation: (specialisationId: string) =>
    apiRequest<SpecialisationApplication>(`/master/specialisations/${specialisationId}/withdraw`, { method: 'POST' }),
  declareCompetency: (serviceId: string) =>
    apiRequest<{ service_id: string; status: string }>('/master/competencies', {
      method: 'POST',
      body: { service_id: serviceId },
    }),
  withdrawCompetency: (serviceId: string) =>
    apiRequest<{ service_id: string; status: string }>(`/master/competencies/${serviceId}/withdraw`, {
      method: 'POST',
    }),
  /** Multipart: the files travel only with the submission they belong to (R-MST-15). */
  submitQualification: ({ qualificationId, documentNumber, validUntil, files }: SubmissionForm) => {
    const body = new FormData()
    body.append('qualification_id', qualificationId)
    if (documentNumber.trim()) body.append('document_number', documentNumber.trim())
    if (validUntil) body.append('valid_until', validUntil)
    for (const file of files) body.append('files', file)
    return apiRequest<Submission>('/master/qualifications', { method: 'POST', body })
  },
  withdrawQualification: (submissionId: string) =>
    apiRequest<Submission>(`/master/qualifications/${submissionId}/withdraw`, { method: 'POST' }),
  /** One of the master's own files; the backend serves only files of the master's own submissions. */
  file: (submissionId: string, fileId: string, mode: 'view' | 'download') =>
    apiBlob(`/master/qualifications/${submissionId}/files/${fileId}?mode=${mode}`),
}

export interface MasterFilters {
  approvalStatus?: MasterApprovalStatus
  hasPending?: boolean
  cursor?: string | null
}

export const adminMastersApi = {
  /** Newest first; `has_pending` = items waiting for a decision (ARCHITECTURE §6b). */
  list: ({ approvalStatus, hasPending, cursor }: MasterFilters) => {
    const params = new URLSearchParams({ limit: '25' })
    if (approvalStatus) params.set('approval_status', approvalStatus)
    if (hasPending !== undefined) params.set('has_pending', String(hasPending))
    if (cursor) params.set('cursor', cursor)
    return apiRequest<Page<AdminMasterListItem>>(`/admin/masters?${params.toString()}`)
  },
  /** Items waiting for a decision across all masters, oldest first. */
  reviewQueue: ({ kind, cursor }: { kind?: QueueKind; cursor?: string | null }) => {
    const params = new URLSearchParams({ limit: '25' })
    if (kind) params.set('kind', kind)
    if (cursor) params.set('cursor', cursor)
    return apiRequest<Page<ReviewQueueItem>>(`/admin/review-queue?${params.toString()}`)
  },
  get: (id: string) => apiRequest<AdminMaster>(`/admin/masters/${id}`),
  // Every decision carries the version the admin saw (stale → 409 VERSION_CONFLICT) and answers with the
  // updated card. Approvals and verifications take no reason; rejections and revocations require one.
  approveProfile: (id: string, expectedVersion: number) =>
    apiRequest<AdminMaster>(`/admin/masters/${id}/approve`, {
      method: 'POST',
      body: { expected_version: expectedVersion },
    }),
  rejectProfile: (id: string, expectedVersion: number, reason: string) =>
    apiRequest<AdminMaster>(`/admin/masters/${id}/reject`, {
      method: 'POST',
      body: { expected_version: expectedVersion, reason },
    }),
  decide: (
    id: string,
    group: DecisionGroup,
    key: string,
    action: DecisionAction,
    expectedVersion: number,
    reason?: string,
  ) =>
    apiRequest<AdminMaster>(`/admin/masters/${id}/${group}/${key}/${action}`, {
      method: 'POST',
      body: reason === undefined ? { expected_version: expectedVersion } : { expected_version: expectedVersion, reason },
    }),
  /** What verifying exactly these competencies together would do; reads only (step 4.4.8). */
  bulkPreview: (id: string, serviceIds: string[]) =>
    apiRequest<BulkPreview>(`/admin/masters/${id}/competencies/bulk-verify/preview`, {
      method: 'POST',
      body: { service_ids: serviceIds },
    }),
  /**
   * Applies a preview, and only a preview: the items and their versions come from it, so nothing is verified
   * that the admin has not seen. All or nothing — a change since the preview is refused as a whole
   * (409 BULK_VERIFY_REJECTED).
   */
  bulkVerify: (id: string, preview: BulkPreview) => {
    const items = preview.items.map((item) => {
      if (!preview.applicable || !item.verifiable || item.expected_version === null) {
        throw new Error('only an applicable preview can be applied')
      }
      return { service_id: item.service_id, expected_version: item.expected_version }
    })
    return apiRequest<AdminMaster>(`/admin/masters/${id}/competencies/bulk-verify`, {
      method: 'POST',
      body: { items, confirm: true },
    })
  },
  /** An evidence file through the admin route; every access is logged by the backend (R-MST-15). */
  file: (id: string, submissionId: string, fileId: string, mode: 'view' | 'download') =>
    apiBlob(`/admin/masters/${id}/qualifications/${submissionId}/files/${fileId}?mode=${mode}`),
}

const CAT = '/admin/catalogue'

/** Entries whose change routes accept `expected_basis` (a category accepts it only on its status change). */
type BasisKind = 'specialisations' | 'services'
type StatusBasisKind = 'categories' | BasisKind
/** `expected_basis` only when given: requests without it stay exactly as before. */
function withBasis(body: Record<string, unknown>, expectedBasis?: BasisItem[]): Record<string, unknown> {
  return expectedBasis === undefined ? body : { ...body, expected_basis: expectedBasis }
}

export const catalogueApi = {
  tree: () => apiRequest<CatalogueTree>(`${CAT}/tree`),
  create: <T>(kind: EntryKind, body: Record<string, unknown>) =>
    apiRequest<T>(`${CAT}/${kind}`, { method: 'POST', body }),
  // Changes carry the version of the entry as loaded; a stale one is refused with 409 VERSION_CONFLICT.
  // Qualification types are edited without it (null); their status changes carry it.
  update: <T, K extends EntryKind = EntryKind>(
    kind: K,
    id: string,
    body: Record<string, unknown>,
    expectedVersion: number | null,
    expectedBasis?: K extends BasisKind ? BasisItem[] : never,
  ) =>
    apiRequest<T>(`${CAT}/${kind}/${id}`, {
      method: 'PATCH',
      body: withBasis(expectedVersion === null ? body : { ...body, expected_version: expectedVersion }, expectedBasis),
    }),
  setStatus: <T, K extends EntryKind = EntryKind>(
    kind: K,
    id: string,
    status: string,
    reason: string | undefined,
    expectedVersion: number,
    expectedBasis?: K extends StatusBasisKind ? BasisItem[] : never,
  ) =>
    apiRequest<T>(`${CAT}/${kind}/${id}/status`, {
      method: 'POST',
      body: withBasis({ status, reason: reason || null, expected_version: expectedVersion }, expectedBasis),
    }),
  activateHold: (id: string, reason: string, expectedVersion: number, expectedBasis?: BasisItem[]) =>
    apiRequest<Service>(`${CAT}/services/${id}/activate-hold`, {
      method: 'POST',
      body: withBasis({ confirm: true, reason, expected_version: expectedVersion }, expectedBasis),
    }),
  setRequirements: <T>(
    kind: BasisKind,
    id: string,
    qualificationIds: string[],
    expectedVersion: number,
    expectedBasis?: BasisItem[],
  ) =>
    apiRequest<T>(`${CAT}/${kind}/${id}/qualifications`, {
      method: 'PUT',
      body: withBasis({ qualification_ids: qualificationIds, expected_version: expectedVersion }, expectedBasis),
    }),
  /** Read-only impact preview; its `basis` goes back as `expectedBasis` with the confirmed change. */
  previewImpact: (request: ImpactRequest) =>
    apiRequest<ImpactResponse>(`${CAT}/impact`, { method: 'POST', body: request }),
  /** `parentPath` is '' for categories, `categories/{id}/specialisations` or `specialisations/{id}/services`. */
  reorder: (parentPath: string, ids: string[]) =>
    apiRequest<void>(parentPath ? `${CAT}/${parentPath}/order` : `${CAT}/categories/order`, {
      method: 'PUT',
      body: { ids },
    }),
  exportPackage: () => apiRequest<Record<string, unknown>>(`${CAT}/export`),
  previewImport: (pkg: unknown) => apiRequest<SyncImport>(`${CAT}/sync-imports`, { method: 'POST', body: pkg }),
  applyImport: (id: string, applyUpdates: string[], keepActive: string[]) =>
    apiRequest<SyncImport>(`${CAT}/sync-imports/${id}/apply`, {
      method: 'POST',
      body: { confirm: true, apply_updates: applyUpdates, keep_active: keepActive },
    }),
}
