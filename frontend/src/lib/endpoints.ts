/**
 * Endpoint wrappers.
 *
 * One function per backend operation the UI uses, so a screen never hand-builds
 * a URL or guesses a query parameter name. Pagination arguments default to the
 * first page at the backend's own page size.
 */

import { api, setTokens, type QueryParams, type TokenPair } from './api'
import type {
  AdminDashboard,
  BuyerDashboard,
  BuyerDemand,
  CommodityOverviewRow,
  Commodity,
  FarmerDashboard,
  FarmLot,
  Grievance,
  GradeSuggestion,
  LogisticsQuoteOption,
  LogisticsRequest,
  Market,
  MarketComparison,
  MarketPrice,
  PriceSnapshot,
  MarketPriceTrend,
  PipelineBucket,
  Transaction,
  MatchResult,
  MatchSummary,
  NotificationList,
  Offer,
  Order,
  Page,
  Payment,
  Profile,
  QualityAttribute,
  QualityInspection,
  StorageFacility,
  UserListItem,
  UserRole,
  UserStatus,
} from './types'

/**
 * Page arguments extend the query record directly, so `page(q)` can spread any
 * filter object without the caller having to restate its pagination fields.
 */
export interface PageQuery extends QueryParams {
  page?: number
  page_size?: number
}

const page = (q: PageQuery = {}): PageQuery => ({ page: 1, page_size: 20, ...q })

export const auth = {
  /** The API field is `identifier`, not `phone`; it accepts a phone or email. */
  async login(identifier: string, password: string): Promise<TokenPair> {
    const tokens = await api.post<TokenPair>('/auth/login', { identifier, password })
    setTokens(tokens)
    return tokens
  },

  async register(body: Record<string, unknown>): Promise<Profile> {
    return api.post<Profile>('/auth/register', body)
  },

  async me(): Promise<Profile> {
    return api.get<Profile>('/auth/me')
  },

  async logout(): Promise<void> {
    // Revoke server-side, but clear locally even if the call fails: a user who
    // clicked "log out" must end up logged out.
    try {
      await api.post('/auth/logout')
    } finally {
      setTokens({ access_token: '', refresh_token: '', token_type: 'bearer', expires_in: 0 })
    }
  },

  async changePassword(current: string, newPassword: string): Promise<void> {
    await api.post('/auth/change-password', {
      current_password: current,
      new_password: newPassword,
    })
  },

  roles: () => api.get<Array<{ name: UserRole; display_name: string; description: string }>>('/auth/roles'),
}

export const dashboards = {
  me: () => api.get<FarmerDashboard | BuyerDashboard | AdminDashboard>('/dashboards/me'),
  farmer: () => api.get<FarmerDashboard>('/dashboards/farmer'),
  buyer: () => api.get<BuyerDashboard>('/dashboards/buyer'),
  admin: () => api.get<AdminDashboard>('/dashboards/admin'),
}

export interface LotFilters extends PageQuery {
  commodity_id?: string
  status?: string
  district?: string
  state?: string
  min_price?: number
  max_price?: number
  min_grade?: string
  organic_certified?: boolean
  search?: string
  sort_by?: string
  near_latitude?: number
  near_longitude?: number
  radius_km?: number
  seller_handles_transport?: boolean
}

export const lots = {
  list: (q: LotFilters = {}) => api.get<Page<FarmLot>>('/lots', page(q)),
  mine: (q: PageQuery = {}) => api.get<Page<FarmLot>>('/lots/mine', page(q)),
  stats: () => api.get<Record<string, unknown>>('/lots/stats'),
  get: (id: string) => api.get<FarmLot>(`/lots/${id}`),
  create: (body: Record<string, unknown>) => api.post<FarmLot>('/lots', body),
  update: (id: string, body: Record<string, unknown>) => api.patch<FarmLot>(`/lots/${id}`, body),
  publish: (id: string) => api.post<FarmLot>(`/lots/${id}/publish`),
  cancel: (id: string, reason?: string) =>
    api.post<FarmLot>(`/lots/${id}/cancel`, reason ? { reason } : {}),
  remove: (id: string) => api.delete<void>(`/lots/${id}`),
  /** A bare list of matches, not a `{summary, results}` envelope. */
  matches: (id: string) => api.get<MatchResult[]>(`/lots/${id}/matches`),
  similar: (id: string) => api.get<Page<FarmLot>>(`/lots/${id}/similar`, { page: 1, page_size: 6 }),
}

/** The signed-in user's matches, whichever side of the trade they sit on. */
export const matches = {
  mine: () => api.get<{ matches: MatchResult[]; summary: MatchSummary }>('/matches'),
}

export const demands = {
  list: (q: PageQuery & { commodity_id?: string; status?: string; district?: string } = {}) =>
    api.get<Page<BuyerDemand>>('/demands', page(q)),
  mine: (q: PageQuery = {}) => api.get<Page<BuyerDemand>>('/demands/mine', page(q)),
  get: (id: string) => api.get<BuyerDemand>(`/demands/${id}`),
  create: (body: Record<string, unknown>) => api.post<BuyerDemand>('/demands', body),
  update: (id: string, body: Record<string, unknown>) => api.patch<BuyerDemand>(`/demands/${id}`, body),
  close: (id: string) => api.post<BuyerDemand>(`/demands/${id}/close`),
  matches: (id: string) => api.get<MatchResult[]>(`/demands/${id}/matches`),
}

export interface OfferFilters extends PageQuery {
  status?: string
  lot_id?: string
  demand_id?: string
  is_buyer?: boolean
}

export const offers = {
  list: (q: OfferFilters = {}) => api.get<Page<Offer>>('/offers', page(q)),
  forLot: (lotId: string) => api.get<Offer[]>(`/offers/lot/${lotId}`),
  get: (id: string) => api.get<Offer>(`/offers/${id}`),
  create: (body: Record<string, unknown>) => api.post<Offer>('/offers', body),
  accept: (id: string, note?: string) => api.post<Offer>(`/offers/${id}/accept`, { note }),
  reject: (id: string, reason: string) => api.post<Offer>(`/offers/${id}/reject`, { reason }),
  counter: (id: string, body: { offered_price: number; quantity?: number; note?: string }) =>
    api.post<Offer>(`/offers/${id}/counter`, body),
  withdraw: (id: string) => api.post<Offer>(`/offers/${id}/withdraw`),
  history: (id: string) => api.get<Offer[]>(`/offers/${id}/history`),
}

export const orders = {
  list: (q: PageQuery & { status?: string; from_date?: string; to_date?: string } = {}) =>
    api.get<Page<Order>>('/orders', page(q)),
  pipeline: () => api.get<PipelineBucket[]>('/orders/pipeline'),
  get: (id: string) => api.get<Order>(`/orders/${id}`),
  transitions: (id: string) => api.get<string[]>(`/orders/${id}/allowed-transitions`),
  updateStatus: (id: string, status: string, note?: string) =>
    api.post<Order>(`/orders/${id}/status`, { status, ...(note ? { note } : {}) }),
  transactions: (id: string) => api.get<Transaction[]>(`/orders/${id}/transactions`),
}

export const markets = {
  list: (q: { district?: string; market_type?: string; term?: string; commodity_id?: string } = {}) =>
    api.get<Market[]>('/markets/markets', q),
  districts: () => api.get<string[]>('/markets/districts'),
  commodities: (term?: string) => api.get<Commodity[]>('/markets/commodities', { term }),
  priceSnapshot: (commodityId: string, district?: string) =>
    api.get<PriceSnapshot>('/markets/price-snapshot', {
      commodity_id: commodityId,
      ...(district ? { district } : {}),
    }),
  latest: (q: { commodity_id?: string; district?: string } = {}) =>
    api.get<MarketPrice[]>('/markets/prices/latest', q),
  trend: (commodityId: string, days = 30, district?: string) =>
    api.get<MarketPriceTrend>('/markets/prices/trend', {
      commodity_id: commodityId,
      days,
      ...(district ? { district } : {}),
    }),
  comparison: (commodityId: string, district?: string) =>
    api.get<MarketComparison>('/markets/prices/comparison', {
      commodity_id: commodityId,
      ...(district ? { district } : {}),
    }),
  prices: (q: {
    commodity_id?: string
    market_id?: string
    district?: string
    from_date?: string
    to_date?: string
    min_price?: number
    max_price?: number
    sort?: string
  } = {}) => api.get<Page<MarketPrice>>('/markets/prices', page(q)),
  arrivals: (commodityId: string, days = 7, district?: string) =>
    api.get<Record<string, unknown>>('/markets/arrivals', {
      commodity_id: commodityId,
      days,
      ...(district ? { district } : {}),
    }),
  overview: (limit = 10) => api.get<CommodityOverviewRow[]>('/markets/overview', { limit }),
}

export const quality = {
  attributes: (commodityId: string) => api.get<QualityAttribute[]>(`/quality/attributes/${commodityId}`),
  suggestGrade: (body: { commodity_id: string; measurements: Array<{ attribute_code: string; value: number }> }) =>
    api.post<GradeSuggestion>('/quality/grade-suggestion', body),
  inspections: (q: PageQuery & { lot_id?: string; status?: string } = {}) =>
    api.get<Page<QualityInspection>>('/quality/inspections', page(q)),
  pending: (q: PageQuery = {}) => api.get<Page<QualityInspection>>('/quality/inspections/pending', page(q)),
  verify: (id: string, body: Record<string, unknown>) =>
    api.post<QualityInspection>(`/quality/inspections/${id}/verify`, body),
}

export const logistics = {
  list: (q: PageQuery & { status?: string } = {}) => api.get<Page<LogisticsRequest>>('/logistics', page(q)),
  get: (id: string) => api.get<LogisticsRequest>(`/logistics/${id}`),
  forOrder: (orderId: string) => api.get<LogisticsRequest>(`/logistics/orders/${orderId}`),
  create: (body: Record<string, unknown>) => api.post<LogisticsRequest>('/logistics', body),
  quote: (body: Record<string, unknown>) => api.post<LogisticsQuoteOption[]>('/logistics/quotes', body),
  assign: (id: string, body: Record<string, unknown>) => api.post<LogisticsRequest>(`/logistics/${id}/assign`, body),
  update: (id: string, body: Record<string, unknown>) => api.patch<LogisticsRequest>(`/logistics/${id}`, body),
  /** `reason` is a query parameter here, not a body field. */
  cancel: (id: string, reason?: string) =>
    api.post<LogisticsRequest>(`/logistics/${id}/cancel${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`),
}

export const storage = {
  options: (q: { commodity_name?: string; min_available_quintal?: number } = {}) =>
    api.get<StorageFacility[]>('/storage/options', q),
  mine: (q: PageQuery = {}) => api.get<Page<StorageFacility>>('/storage/mine', page(q)),
  list: (q: PageQuery = {}) => api.get<Page<StorageFacility>>('/storage', page(q)),
  create: (body: Record<string, unknown>) => api.post<StorageFacility>('/storage', body),
  update: (id: string, body: Record<string, unknown>) => api.patch<StorageFacility>(`/storage/${id}`, body),
}

/**
 * The summary endpoints are untyped dicts on the backend (`dict[str, Any]`), so
 * the shapes below are this module's reading of the service. Keep them in step
 * with `PaymentService.summary_for` / `platform_summary` if either changes.
 */
export interface PaymentSummary {
  total_expected?: number
  total_paid?: number
  total_pending?: number
  overdue_amount?: number
  overdue_count?: number
  [key: string]: unknown
}

export const payments = {
  list: (q: PageQuery & { status?: string; overdue_only?: boolean } = {}) =>
    api.get<Page<Payment>>('/payments', page(q)),
  summary: () => api.get<PaymentSummary>('/payments/summary'),
  platformSummary: () => api.get<PaymentSummary>('/payments/summary/platform'),
  dueSoon: (days = 7) => api.get<Payment[]>('/payments/due-soon', { days }),
  updateStatus: (id: string, body: Record<string, unknown>) => api.patch<Payment>(`/payments/${id}/status`, body),
}

export const grievances = {
  list: (q: PageQuery & { status?: string; category?: string } = {}) =>
    api.get<Page<Grievance>>('/grievances', page(q)),
  summary: () => api.get<Record<string, unknown>>('/grievances/summary'),
  comments: (id: string) => api.get<Array<Record<string, unknown>>>(`/grievances/${id}/comments`),
  create: (body: Record<string, unknown>) => api.post<Grievance>('/grievances', body),
  get: (id: string) => api.get<Grievance>(`/grievances/${id}`),
  escalate: (id: string, reason: string) => api.post<Grievance>(`/grievances/${id}/escalate`, { reason }),
}

/** Notifications are the one list endpoint the backend does not paginate. */
export const notifications = {
  list: (q: { unread_only?: boolean } = {}) => api.get<NotificationList>('/notifications', q),
  unreadCount: () => api.get<{ unread_count: number }>('/notifications/unread-count'),
  markRead: (id: string) => api.post<void>(`/notifications/${id}/read`),
  markAllRead: () => api.post<{ updated: number }>('/notifications/read-all'),
}

export const admin = {
  users: (q: PageQuery & { role?: UserRole; status?: UserStatus; search?: string } = {}) =>
    api.get<Page<UserListItem>>('/admin/users', page(q)),
  userCounts: () => api.get<Record<string, number>>('/admin/users/counts'),
  user: (id: string) => api.get<UserListItem>(`/admin/users/${id}`),
  setUserStatus: (id: string, status: UserStatus, reason?: string) =>
    api.patch<UserListItem>(`/admin/users/${id}/status`, { status, ...(reason ? { reason } : {}) }),
  verifyBuyer: (id: string, body: { approve: boolean; notes?: string }) =>
    api.post<UserListItem>(`/admin/users/${id}/verify-buyer`, body),
  health: () => api.get<Record<string, unknown>>('/admin/health'),
  auditLogs: (q: PageQuery & { entity_type?: string; action?: string } = {}) =>
    api.get<Page<Record<string, unknown>>>('/admin/audit-logs', page(q)),
  commodities: (body?: Record<string, unknown>) => api.post<Commodity>('/admin/commodities', body),
  markets: () => api.get<Market[]>('/admin/markets'),
  syncLogs: (q: PageQuery = {}) => api.get<Page<Record<string, unknown>>>('/admin/market-data/sync-logs', page(q)),
}
