import type {
  AdminCommissionDetail,
  AdminMasterWork,
  AdminCommissionRow,
  AdminRequestDetail,
  AdminRequestRow,
  AppNotification,
  ClientRequest,
  CityApi,
  ClientRequestListItem,
  CommercialTermsRow,
  CommunicationLanguageApi,
  ContentData,
  ContentListItem,
  ContentPage,
  LocalizedApi,
  MasterCommission,
  MasterOrder,
  MediaItem,
  PublicCatalogueApi,
  PublicTerms,
  RequestCreatePayload,
  SpecialisationPageApi,
  StatsOverview,
  WorkProfile,
} from '../types/work'
import { apiBlob, apiRequest } from './client'

export const publicApi = {
  catalogue: () => apiRequest<PublicCatalogueApi>('/public/catalogue'),
  specialisation: (slug: string) => apiRequest<SpecialisationPageApi>(`/public/specialisations/${encodeURIComponent(slug)}`),
  cities: () => apiRequest<CityApi[]>('/public/cities'),
  languages: () => apiRequest<CommunicationLanguageApi[]>('/public/communication-languages'),
  terms: (lang: string) => apiRequest<PublicTerms>(`/public/commercial-terms?lang=${lang}`),
  event: (event_type: 'catalogue_view' | 'specialisation_view' | 'service_selected', entity_id?: string, source?: 'web' | 'app') =>
    apiRequest<void>('/public/events', { method: 'POST', body: { event_type, entity_id, source } }),
}

export const clientApi = {
  create: (body: RequestCreatePayload) => apiRequest<ClientRequest>('/client/requests', { method: 'POST', body }),
  list: () => apiRequest<ClientRequestListItem[]>('/client/requests'),
  get: (id: string) => apiRequest<ClientRequest>(`/client/requests/${id}`),
  addPhoto: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest<{ id: string }>(`/client/requests/${id}/photos`, { method: 'POST', body: form })
  },
  deletePhoto: (id: string, fileId: string) => apiRequest<void>(`/client/requests/${id}/photos/${fileId}`, { method: 'DELETE' }),
  photo: (id: string, fileId: string) => apiBlob(`/client/requests/${id}/photos/${fileId}`),
  submit: (id: string) => apiRequest<ClientRequest>(`/client/requests/${id}/submit`, { method: 'POST' }),
  cancel: (id: string, reason?: string) => apiRequest<ClientRequest>(`/client/requests/${id}/cancel`, { method: 'POST', body: { reason } }),
  confirm: (id: string, candidate_id: string) =>
    apiRequest<ClientRequest>(`/client/requests/${id}/confirm`, { method: 'POST', body: { candidate_id } }),
  reject: (id: string) => apiRequest<ClientRequest>(`/client/requests/${id}/reject`, { method: 'POST' }),
  review: (orderId: string, rating: number, comment?: string) =>
    apiRequest<{ id: string }>(`/client/orders/${orderId}/review`, { method: 'POST', body: { rating, comment } }),
}

export const notificationsApi = {
  list: () => apiRequest<AppNotification[]>('/notifications'),
  read: (ids?: string[]) => apiRequest<void>('/notifications/read', { method: 'POST', body: { ids } }),
}

export type OrderAction = 'accept' | 'depart' | 'arrive' | 'start' | 'pause' | 'resume' | 'finish' | 'finalise'

export const workApi = {
  profile: () => apiRequest<WorkProfile>('/master/work-profile'),
  setMode: (mode: WorkProfile['availability_mode']) => apiRequest<WorkProfile>('/master/availability', { method: 'PUT', body: { mode } }),
  setCity: (city: string) => apiRequest<WorkProfile>('/master/work-city', { method: 'PUT', body: { city } }),
  setLanguages: (languages: string[]) => apiRequest<WorkProfile>('/master/languages', { method: 'PUT', body: { languages } }),
  setDescription: (description: string) =>
    apiRequest<WorkProfile>('/master/profile-description', { method: 'PUT', body: { description } }),
  sendLocation: (lat: number, lon: number, accuracy_m?: number) =>
    apiRequest<void>('/master/location', {
      method: 'POST',
      body: { lat: lat.toFixed(6), lon: lon.toFixed(6), accuracy_m: accuracy_m === undefined ? undefined : Math.round(accuracy_m) },
    }),
  offers: () => apiRequest<MasterOrder[]>('/master/offers'),
  orders: (scope: 'active' | 'history') => apiRequest<MasterOrder[]>(`/master/orders?scope=${scope}`),
  order: (id: string) => apiRequest<MasterOrder>(`/master/orders/${id}`),
  action: (id: string, action: OrderAction) => apiRequest<MasterOrder>(`/master/orders/${id}/${action}`, { method: 'POST' }),
  decline: (id: string, reason?: string) => apiRequest<MasterOrder>(`/master/orders/${id}/decline`, { method: 'POST', body: { reason } }),
  cancel: (id: string, reason: string) => apiRequest<MasterOrder>(`/master/orders/${id}/cancel`, { method: 'POST', body: { reason } }),
  worksheet: (id: string, body: unknown) => apiRequest<MasterOrder>(`/master/orders/${id}/worksheet`, { method: 'PUT', body }),
  photo: (id: string, fileId: string) => apiBlob(`/master/orders/${id}/photos/${fileId}`),
  commission: () => apiRequest<MasterCommission>('/master/commission'),
}

export const adminWorkApi = {
  terms: () => apiRequest<CommercialTermsRow[]>('/admin/commercial-terms'),
  createTerms: (body: { hourly_rate_eur: string; minimum_order_eur: string; materials_note: LocalizedApi; reason: string }) =>
    apiRequest<CommercialTermsRow>('/admin/commercial-terms', { method: 'POST', body }),
  media: () => apiRequest<MediaItem[]>('/admin/media'),
  uploadMedia: (form: FormData) => apiRequest<MediaItem>('/admin/media', { method: 'POST', body: form }),
  archiveMedia: (id: string, reason: string) => apiRequest<MediaItem>(`/admin/media/${id}/archive`, { method: 'POST', body: { reason } }),
  withdrawConsent: (id: string, reason: string) =>
    apiRequest<MediaItem>(`/admin/media/${id}/withdraw-consent`, { method: 'POST', body: { reason } }),
  contentList: () => apiRequest<ContentListItem[]>('/admin/content'),
  content: (specId: string) => apiRequest<ContentPage>(`/admin/content/${specId}`),
  saveDraft: (specId: string, data: ContentData, expected_version: number) =>
    apiRequest<ContentPage>(`/admin/content/${specId}/draft`, { method: 'PUT', body: { data, expected_version } }),
  publish: (specId: string, expected_version: number) =>
    apiRequest<ContentPage>(`/admin/content/${specId}/publish`, { method: 'POST', body: { expected_version } }),
  unpublish: (specId: string, expected_version: number) =>
    apiRequest<ContentPage>(`/admin/content/${specId}/unpublish`, { method: 'POST', body: { expected_version } }),
  restore: (specId: string, versionId: string, expected_version: number) =>
    apiRequest<ContentPage>(`/admin/content/${specId}/versions/${versionId}/restore`, { method: 'POST', body: { expected_version } }),
  setSlug: (specId: string, slug: string, expected_version: number) =>
    apiRequest<ContentPage>(`/admin/content/${specId}/slug`, { method: 'PUT', body: { slug, expected_version } }),
  commission: () => apiRequest<AdminCommissionRow[]>('/admin/commission/masters'),
  commissionMaster: (id: string) => apiRequest<AdminCommissionDetail>(`/admin/commission/masters/${id}`),
  // `key` stays the same for retries of one submission, so a double click or a lost answer never books it twice.
  payment: (
    id: string,
    body: { amount_eur: string; paid_on: string; payment_method: 'cash' | 'bank_transfer'; reference?: string; comment?: string },
    key: string,
  ) =>
    apiRequest<AdminCommissionDetail>(`/admin/commission/masters/${id}/payments`, { method: 'POST', body, headers: { 'Idempotency-Key': key } }),
  adjustment: (id: string, amount_eur: string, reason: string, key: string) =>
    apiRequest<AdminCommissionDetail>(`/admin/commission/masters/${id}/adjustments`, {
      method: 'POST',
      body: { amount_eur, reason },
      headers: { 'Idempotency-Key': key },
    }),
  masterWork: (id: string) => apiRequest<AdminMasterWork>(`/admin/masters/${id}/work`),
  limit: (id: string, new_limit_eur: string, reason: string) =>
    apiRequest<AdminCommissionDetail>(`/admin/commission/masters/${id}/limit`, { method: 'POST', body: { new_limit_eur, reason } }),
  requests: (status?: string) => apiRequest<AdminRequestRow[]>(`/admin/requests${status ? `?status=${status}` : ''}`),
  request: (id: string) => apiRequest<AdminRequestDetail>(`/admin/requests/${id}`),
  cancelRequest: (id: string, reason: string) =>
    apiRequest<AdminRequestDetail>(`/admin/requests/${id}/cancel`, { method: 'POST', body: { reason } }),
  stats: (days = 30) => apiRequest<StatsOverview>(`/admin/stats/overview?days=${days}`),
  settings: () => apiRequest<Record<string, unknown>>('/admin/settings'),
  putBillableRule: (rounding: string, step_minutes: number, reason: string) =>
    apiRequest<Record<string, unknown>>('/admin/settings/billable-time/rule', { method: 'PUT', body: { rounding, step_minutes, reason } }),
  confirmPolicy: (policy: string, confirmed: boolean, reason: string) =>
    apiRequest<Record<string, unknown>>('/admin/settings/policy-confirmation', { method: 'POST', body: { policy, confirmed, reason } }),
  putSetting: (key: string, value: number, reason: string) =>
    apiRequest<Record<string, unknown>>(`/admin/settings/${key}`, { method: 'PUT', body: { value, reason } }),
}
