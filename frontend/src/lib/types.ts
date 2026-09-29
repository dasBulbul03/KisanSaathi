/**
 * Response shapes, transcribed from the backend's OpenAPI document.
 *
 * Deliberately hand-written rather than generated. The backend's generated
 * types would be more complete but would also mean a codegen step in the build;
 * these are the fields the UI actually reads, and anything else stays out of the
 * way. When a screen needs a new field, add it here next to the backend change
 * so the two stay in step.
 */

import type { TokenPair } from './api'

export type { TokenPair }

export type UserRole =
  | 'FARMER'
  | 'FPO'
  | 'BUYER'
  | 'ADMIN'
  | 'LOGISTICS_PARTNER'
  | 'QUALITY_INSPECTOR'

export type OrderStatus =
  | 'OFFER_ACCEPTED'
  | 'ORDER_CREATED'
  | 'LOGISTICS_ASSIGNED'
  | 'PICKUP_SCHEDULED'
  | 'IN_TRANSIT'
  | 'DELIVERED'
  | 'QUALITY_CONFIRMED'
  | 'PAYMENT_PENDING'
  | 'PAYMENT_COMPLETED'
  | 'COMPLETED'
  | 'CANCELLED'

export type QualityGrade = 'A' | 'B' | 'C'
export type LotStatus =
  | 'DRAFT'
  | 'PUBLISHED'
  | 'UNDER_OFFER'
  | 'SOLD'
  | 'IN_TRANSIT'
  | 'COMPLETED'
  | 'CANCELLED'
export type OfferStatus =
  | 'PENDING'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'COUNTERED'
  | 'WITHDRAWN'
  | 'EXPIRED'
export type DemandStatus =
  | 'OPEN'
  | 'PARTIALLY_FULFILLED'
  | 'FULFILLED'
  | 'CLOSED'
  | 'EXPIRED'
export type PaymentStatus = 'PENDING' | 'PROCESSING' | 'PAID' | 'FAILED' | 'DISPUTED'
export type SellerType = 'FARMER' | 'FPO'
export type BuyerType = 'RETAILER' | 'WHOLESALER' | 'PROCESSOR' | 'EXPORT_TRADER' | 'INSTITUTION'
export type StorageType = 'OWN_GODOWN' | 'RENTED_GODOWN' | 'FPO_STORE' | 'COLD_STORAGE' | 'OPEN_STORAGE'
export type VerificationStatus = 'PENDING' | 'VERIFIED' | 'REJECTED'
export type UserStatus = 'ACTIVE' | 'PENDING' | 'SUSPENDED' | 'INACTIVE'
export type PriceSource =
  | 'DEMO'
  | 'AGMARKET_API'
  | 'STATE_APMC'
  | 'MANUAL'
  | 'PARTNER_API'
export type MarketType =
  | 'APMC_MANDI'
  | 'FARM_GATE'
  | 'COLLECTION_CENTRE'
  | 'ORGANIC_MANDI'
  | 'PRIVATE_HUB'

export interface PaginationMeta {
  page: number
  page_size: number
  total_items: number
  total_pages: number
  has_next: boolean
  has_previous: boolean
}

/** Every list endpoint returns this shape. */
export interface Page<T> {
  items: T[]
  meta: PaginationMeta
}

export interface UserSummary {
  id: string
  full_name: string
  phone: string
  email: string | null
  avatar_url: string | null
  district: string | null
  state: string | null
  role: UserRole
  status: UserStatus
  is_email_verified: boolean
  is_phone_verified: boolean
}

export interface FarmerProfile {
  id: string
  farmer_id_code: string | null
  village: string | null
  taluka: string | null
  district: string | null
  state: string | null
  pincode: string | null
  latitude: number | null
  longitude: number | null
  farm_area_acres: number | null
  farming_since: number | null
  irrigation_source: string | null
  primary_crops: string[]
  annual_production_quintal: number | null
  storage_available: boolean | null
  storage_capacity_quintal: number | null
  upi_id: string | null
  bank_name: string | null
  bank_account_last4: string | null
  ifsc_code: string | null
  kcc_number: string | null
}

export interface FPOProfile {
  id: string
  organisation_name: string
  registration_number: string | null
  village: string | null
  taluka: string | null
  district: string | null
  state: string | null
  member_count: number | null
  women_member_count: number | null
  commodities: string[]
  aggregate_capacity_quintal: number | null
  storage_capacity_quintal: number | null
  cold_storage_units: number | null
  contact_person: string | null
  contact_phone: string | null
}

export interface BuyerProfile {
  id: string
  organisation_name: string
  buyer_type: BuyerType
  gst_number: string | null
  fssai_licence: string | null
  verification_status: VerificationStatus
  verified_at: string | null
  verification_notes: string | null
  commodities: string[]
  monthly_volume_quintal: number | null
  quality_requirements: string | null
  payment_terms: string | null
  default_payment_terms_days: number | null
  district: string | null
  taluka: string | null
  city: string | null
  state: string | null
  contact_person: string | null
  website: string | null
}

export interface Profile {
  user: UserSummary
  farmer: FarmerProfile | null
  fpo: FPOProfile | null
  buyer: BuyerProfile | null
  permissions: string[]
}

export interface RoleOption {
  name: UserRole
  display_name: string
  description: string
  permissions: string[]
}

export interface Commodity {
  id: string
  name: string
  code: string
  name_hindi: string | null
  name_marathi: string | null
  category: string
  default_unit: string
  permitted_units: string[] | null
  is_perishable: boolean
  shelf_life_days: number | null
  seasonality_note: string | null
  description: string | null
  is_active?: boolean
}

export interface Market {
  id: string
  code?: string
  name: string
  market_type: MarketType
  district: string | null
  taluka: string | null
  state: string | null
  latitude: number | null
  longitude: number | null
  apmc_number?: string | null
  has_storage?: boolean
  has_weighbridge?: boolean
  trading_hours?: string | null
  is_active?: boolean
}

export interface MarketPrice {
  id: string
  market_id: string
  market_name: string | null
  market_type: MarketType | null
  commodity_id: string
  commodity_name: string | null
  price_date: string
  min_price: number
  max_price: number
  modal_price: number
  arrivals_quantity: number | null
  arrivals_unit: string | null
  unit: string | null
  source: PriceSource
  is_demo: boolean
}

/**
 * One market's price row inside a snapshot. Note the date field is `date`, not
 * `price_date`, and rows are identified by `market_id` because a snapshot
 * deliberately groups several markets under one commodity.
 */
export interface MarketSnapshotRow {
  market_id: string
  market_name: string
  district: string | null
  market_type: string
  date: string
  min_price: number
  max_price: number
  modal_price: number
  arrivals_quantity: number | null
  unit: string | null
  distance_km: number | null
  is_demo: boolean
  change_pct_7d: number | null
}

/** `/markets/price-snapshot` returns an object, not a bare list. */
export interface PriceSnapshot {
  commodity_id: string
  commodity_name: string | null
  unit: string | null
  as_of: string
  markets: MarketSnapshotRow[]
}

export interface MarketPriceTrendPoint {
  /** The trend API calls this `date`, not `price_date`. */
  date: string
  min_price: number
  max_price: number
  modal_price: number
  arrivals_quantity: number | null
  /** How many markets contributed to this day's point. */
  market_count: number | null
}

export interface MarketPriceTrend {
  commodity_id: string
  commodity_name: string
  unit: string
  from_date: string
  to_date: string
  points: MarketPriceTrendPoint[]
  district_median_modal_price: number | null
  overall_change_pct: number | null
  is_demo_data: boolean
  disclaimer: string
}

export interface MarketComparisonRow {
  market_id: string
  market_name: string
  district: string | null
  modal_price: number
  min_price: number
  max_price: number
  distance_km: number | null
  arrivals_quantity: number | null
  change_pct_7d: number | null
}

export interface MarketComparison {
  commodity_id: string
  commodity_name: string
  price_date: string
  rows: MarketComparisonRow[]
  best_market_id: string | null
  nearest_market_id: string | null
  is_demo_data: boolean
  disclaimer: string
}

export interface SellerSummary {
  id: string
  full_name: string
  organisation_name: string | null
  district: string | null
  village: string | null
  is_verified: boolean
  rating: number | null
}

export interface FarmLot {
  id: string
  lot_code: string
  seller_type: SellerType
  seller_user_id: string
  commodity_id: string
  commodity_name: string | null
  commodity_category: string | null
  title: string
  description: string | null
  quantity: number
  available_quantity: number
  unit: string
  expected_price: number | null
  minimum_price: number | null
  quality_grade: QualityGrade
  quality_specs: Record<string, unknown> | null
  harvest_date: string | null
  available_from: string | null
  village: string | null
  taluka: string | null
  district: string | null
  state: string | null
  latitude: number | null
  longitude: number | null
  storage_available: boolean | null
  organic_certified: boolean | null
  pickup_available: boolean | null
  seller_handles_transport: boolean | null
  status: LotStatus
  published_at: string | null
  view_count: number | null
  active_offers_count: number | null
  created_at: string
  updated_at: string
  images?: LotImage[]
  seller?: SellerSummary
  latest_market_price?: MarketPrice | null
  market_price_source_market?: string | null
  distance_km?: number | null
  inspection_grade?: QualityGrade | null
}

export interface LotImage {
  id: string
  image_url: string
  caption: string | null
  sort_order: number
}

export interface BuyerDemand {
  id: string
  reference_code: string
  buyer_user_id: string
  buyer_name: string | null
  buyer_organisation: string | null
  buyer_verified: boolean | null
  commodity_id: string
  commodity_name: string | null
  required_quantity: number
  fulfilled_quantity: number | null
  unit: string
  min_grade: QualityGrade
  min_price_per_unit: number | null
  max_price_per_unit: number | null
  delivery_location: string
  district: string | null
  taluka: string | null
  city: string | null
  max_pickup_radius_km: number | null
  required_by_date: string
  delivery_window_days: number | null
  payment_terms: string | null
  payment_terms_days: number | null
  requires_verified_buyer: boolean | null
  status: DemandStatus
  notes: string | null
  active_offers_count: number | null
  matched_lots_count: number | null
  created_at: string
}

export interface Offer {
  id: string
  reference_code: string
  lot_id: string
  lot_code: string | null
  lot_title: string | null
  commodity_id: string | null
  commodity_name: string | null
  buyer_user_id: string
  buyer_name: string | null
  buyer_organisation: string | null
  buyer_verified: boolean | null
  demand_id: string | null
  offered_price: number
  quantity: number
  unit: string
  delivery_terms: string | null
  payment_terms: string | null
  payment_terms_days: number | null
  valid_until: string | null
  notes: string | null
  status: OfferStatus
  parent_offer_id: string | null
  responded_at: string | null
  decline_reason: string | null
  total_value: number | null
  created_at: string
  is_buyer: boolean
  is_seller: boolean
  can_respond: boolean
}

export interface OrderStatusHistoryEntry {
  status: OrderStatus
  at: string
  by: string | null
  note: string | null
}

export interface Order {
  id: string
  order_number: string
  offer_id: string
  lot_id: string
  lot_code: string | null
  buyer_user_id: string
  buyer_name: string | null
  buyer_organisation: string | null
  seller_user_id: string
  seller_name: string | null
  seller_organisation: string | null
  commodity_id: string
  commodity_name: string | null
  quantity: number
  unit: string
  agreed_price: number
  total_value: number
  quality_grade: QualityGrade
  status: OrderStatus
  pickup_location: string
  pickup_district: string | null
  delivery_location: string
  delivery_district: string | null
  pickup_date: string | null
  delivery_date: string | null
  payment_terms_days: number | null
  status_history: OrderStatusHistoryEntry[] | null
  cancelled_reason: string | null
  logistics_status: string | null
  logistics_reference: string | null
  payment_status: PaymentStatus | null
  payment_due_date: string | null
  created_at: string
  updated_at: string
}

export interface PipelineBucket {
  status: OrderStatus
  count: number
  value: number
}

export interface Payment {
  id: string
  transaction_id: string | null
  transaction_reference: string | null
  order_id: string | null
  order_number: string | null
  payer_user_id: string | null
  payer_name: string | null
  payee_user_id: string | null
  payee_name: string | null
  amount: number
  currency: string
  status: PaymentStatus
  method: string | null
  due_date: string | null
  reference_number: string | null
  initiated_at: string | null
  paid_at: string | null
  failure_reason: string | null
  notes: string | null
  is_demo: boolean
  created_at: string
}

export interface Transaction {
  id: string
  transaction_reference: string
  order_id: string
  order_number: string | null
  seller_name: string | null
  buyer_name: string | null
  commodity_name: string | null
  quantity: number
  unit: string
  unit_price: number
  total_amount: number
  platform_fee: number
  status: string
  district: string | null
  initiated_at: string | null
  completed_at: string | null
  payment_status: PaymentStatus | null
  amount_paid: number
}

export interface StorageFacility {
  id: string
  owner_user_id: string
  owner_name: string | null
  name: string
  storage_type: StorageType
  capacity_quintal: number
  occupied_quintal: number
  available_quintal: number | null
  village: string | null
  taluka: string | null
  district: string | null
  state: string | null
  latitude: number | null
  longitude: number | null
  storage_cost_per_quintal_month: number | null
  temperature_controlled: boolean | null
  supports_commodities: string[] | null
  amenities: string[] | null
  contact_person: string | null
  contact_phone: string | null
  is_private: boolean
  distance_km: number | null
  created_at: string
}

export interface DashboardStat {
  label: string
  value: number
  display: string
  unit?: string | null
  change_pct?: number | null
  trend?: string | null
  hint?: string | null
}

export interface MarketInsightCard {
  kind: string
  title: string
  message: string
  tone?: string | null
  action_label?: string | null
  action_href?: string | null
  confidence?: string | null
}

export interface NotificationItem {
  id: string
  title: string
  body: string
  notification_type: string
  /** Route the notification links to, e.g. `/orders/...`. */
  link: string | null
  /** Type-specific payload: the order id, offer id, lot id and so on. */
  data: Record<string, unknown>
  is_read: boolean
  read_at: string | null
  created_at: string
}

/** The feed is not paginated; it carries its own unread tally. */
export interface NotificationList {
  items: NotificationItem[]
  unread_count: number
}

export interface LogisticsQuoteOption {
  provider_name: string
  vehicle_type: string
  distance_km: number
  estimated_cost: number
  transit_days: number
  rating: number | null
  is_demo: boolean
  note: string | null
}

export interface FarmerDashboard {
  generated_at: string
  greeting: string
  seller: {
    id: string
    full_name: string
    role: string
    district: string | null
    village: string | null
    organisation_name: string | null
    farmer_id_code: string | null
    primary_crops: string[]
  }
  stats: DashboardStat[]
  price_cards: PriceCard[]
  insights: MarketInsightCard[]
  active_lots: FarmLot[]
  recent_offers: Offer[]
  order_pipeline: PipelineBucket[]
  notifications: NotificationItem[]
  is_demo_data: boolean
}

export interface PriceCard {
  commodity_id: string
  commodity_name: string
  unit: string
  modal_price: number | null
  min_price: number | null
  max_price: number | null
  price_date: string | null
  arrivals_quintal: number | null
  change_pct_7d: number | null
  trend: 'up' | 'down' | 'flat'
  my_lots: number
  /** Markets the rate covers. Null for cards that come from a single commodity. */
  market_count?: number | null
}

/**
 * A row from `/markets/overview`. Named after the API, not reshaped into
 * PriceCard: the overview reports `commodity` and `median_modal_price`, and the
 * two are genuinely different things (a median across markets versus the modal
 * rate for one). Callers that want a card convert it explicitly.
 */
export interface CommodityOverviewRow {
  commodity_id: string
  commodity: string
  category: string
  unit: string
  median_modal_price: number | null
  min_modal: number | null
  max_modal: number | null
  change_pct_7d: number | null
  market_count: number
  is_demo_data: boolean
}

export interface BuyerDashboard {
  generated_at: string
  buyer: {
    id: string
    full_name: string
    organisation_name: string | null
    district: string | null
    verification_status: VerificationStatus
  }
  stats: DashboardStat[]
  /**
   * The buyer dashboard has no price cards or insights of its own: the insight
   * rules are written for sellers (publish your draft, answer this offer). Rate
   * context for a buyer comes from `/markets/overview` instead.
   */
  open_demands: BuyerDemand[]
  recent_lots: FarmLot[]
  offers: Offer[]
  orders: Order[]
  recommended_lots: MatchResult[]
  notifications: NotificationItem[]
  is_demo_data: boolean
}

/**
 * One shape for matching results in either direction.
 *
 * `entity_type` is "lot" when matching a demand to supply, "demand" when
 * matching a lot to buyer demand. `score_label` ("strong"/"good"/"possible")
 * is computed server-side and is the value the UI should rank and colour by,
 * rather than re-deriving a threshold here.
 */
export interface MatchResult {
  entity_type: 'lot' | 'demand' | string
  entity_id: string
  reference_code: string | null
  title: string | null
  score: number
  score_label: string
  commodity: string | null
  quantity: number | null
  unit: string | null
  grade: QualityGrade | null
  expected_price: number | null
  price_range: string | null
  district: string | null
  location: string | null
  distance_km: number | null
  is_verified_buyer: boolean | null
  seller_name: string | null
  seller_organisation: string | null
  completed_orders: number | null
  rating: number | null
  required_by_date: string | null
  available_from: string | null
  reasons: string[]
  warnings: string[]
  disclaimer: string
}

export interface MatchSummary {
  direction: string
  total_candidates: number
  strong_matches: number
  generated_at: string
  disclaimer: string
}

export interface AdminDashboard {
  generated_at: string
  stats: DashboardStat[]
  registrations: {
    by_role: Record<string, number>
    active_users: number
    new_last_30_days: number
    by_district: Record<string, number>
  }
  trade: {
    trade_value_30d: number
    trade_value_90d: number
    completed_orders: number
    pending_orders: number
    payments: Record<string, number>
  }
  /**
   * These rows are untyped dicts on the server, so the field names here are the
   * contract. A backend test asserts every row carries them, because a mismatch
   * is invisible: the table still renders, just empty.
   */
  demand_by_commodity: Array<{
    commodity_id: string
    commodity_name: string
    open_demands: number
    demanded_quintal: number
    active_lots: number
    listed_quintal: number
    median_modal_price: number | null
    demand_level: string
    demand_supply_ratio: number | null
  }>
  activity_by_district: Array<{
    district: string
    users: number
    farmers: number
    fpos: number
    active_lots: number
    trade_value: number
    avg_price: number | null
    top_commodity: string | null
  }>
  price_movement: Array<{
    commodity_id: string
    commodity_name: string
    modal_price: number | null
    change_pct_7d: number | null
    direction: 'up' | 'down' | 'flat'
    as_of: string | null
  }>
  pending_actions: {
    open_grievances: number
    unassigned_logistics: number
    pending_inspections: number
    pending_buyers: number
  }
  system_health: {
    database: string
    commodities: number
    districts: number
    demo_price_data: boolean
  }
  is_demo_data: boolean
}

export interface Grievance {
  id: string
  ticket_number: string
  category: string
  subject: string
  description: string
  status: string
  priority: string
  order_id: string | null
  raised_by_user_id: string
  raised_by_name: string | null
  assigned_to_name: string | null
  resolution_notes: string | null
  escalated_at: string | null
  created_at: string
  updated_at: string
}

export interface LogisticsRequest {
  id: string
  reference_code: string
  order_id: string
  order_number: string | null
  commodity_name: string | null
  provider_user_id: string
  provider_name: string | null
  status: string
  pickup_location: string
  pickup_district: string | null
  destination: string
  destination_district: string | null
  distance_km: number | null
  quantity: number | null
  unit: string | null
  vehicle_type: string | null
  vehicle_number: string | null
  estimated_cost: number | null
  actual_cost: number | null
  transporter_name: string | null
  transporter_contact: string | null
  pickup_date: string | null
  delivery_date: string | null
  tracking_number: string | null
  cold_chain_required: boolean | null
  status_history: Array<Record<string, unknown>> | null
  created_at: string
  updated_at: string
}

export interface QualityInspection {
  id: string
  lot_id: string
  order_id: string | null
  inspector_user_id: string
  inspector_name: string | null
  inspection_type: string
  inspected_at: string
  grade: QualityGrade
  status: string
  attributes: Record<string, unknown> | null
  moisture_percent: number | null
  damage_percent: number | null
  notes: string | null
  is_demo: boolean
  created_at: string
  measurements: Array<Record<string, unknown>> | null
}

export interface GradeCheck {
  code: string
  label: string
  unit: string
  value: number
  ideal_min: number | null
  ideal_max: number | null
  satisfied: boolean
}

export interface GradeSuggestion {
  suggested_grade: QualityGrade | null
  reason: string
  checks: GradeCheck[]
}

export interface QualityAttribute {
  id: string
  commodity_id: string
  code: string
  label: string
  unit: string
  ideal_min: number | null
  ideal_max: number | null
  grade_a_min: number | null
  grade_b_min: number | null
  is_active: boolean
  sort_order: number
}

export interface UserListItem {
  id: string
  full_name: string
  phone: string
  email: string | null
  role: UserRole
  status: UserStatus
  district: string | null
  organisation_name: string | null
  verification_status: VerificationStatus | null
  created_at: string
  last_login_at: string | null
}
