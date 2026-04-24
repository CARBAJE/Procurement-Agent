// Mirrors Bap-1/src/beckn/models.py and IntentParser/schemas.py
export interface BudgetConstraints {
  max: number
  min?: number
}

export interface BecknIntent {
  item: string
  descriptions: string[]
  quantity: number
  unit: string
  location_coordinates: string  // "lat,lon"
  delivery_timeline: number     // hours (72 = 3 days)
  budget_constraints: BudgetConstraints
}

export type ParsedIntentType = "procurement" | "unknown"

export interface ParseResult {
  intent: ParsedIntentType
  confidence: number
  beckn_intent: BecknIntent | null
  routed_to: string
}

export interface Offering {
  bpp_id: string
  bpp_uri?: string
  provider_id: string
  provider_name: string
  item_id: string
  item_name: string
  price_value: string
  price_currency: string
  rating?: string | null
  fulfillment_hours?: number | null
  specifications?: string[]
  available_quantity?: number | null
}

// ── Reasoning trace (structured) ────────────────────────────────────────────

export type ReasoningRole = "reason" | "act" | "observe"

export interface ReasoningStep {
  node: string
  role: ReasoningRole | string
  summary: string
  details?: Record<string, unknown>
  timestamp: string
}

// ── Scoring (multi-criterion-ready, one criterion today) ────────────────────

export interface ScoringRow {
  item_id: string
  raw: string
  normalized: number
  explanation: string
}

export interface ScoringCriterion {
  key: string
  label: string
  weight: number
  direction: "min" | "max"
  scores: ScoringRow[]
}

export interface ScoringRanking {
  item_id: string
  composite_score: number
  rank: number
}

export interface Scoring {
  recommended_item_id: string | null
  criteria: ScoringCriterion[]
  ranking: ScoringRanking[]
}

// ── /compare, /commit, /status response shapes ──────────────────────────────

export interface ComparisonResult {
  transaction_id: string
  offerings: Offering[]
  recommended_item_id: string | null
  scoring: Scoring
  reasoning_steps: ReasoningStep[]
  messages: string[]
  status: "live" | "mock"
}

export type OrderState =
  | "CREATED"
  | "ACCEPTED"
  | "PACKED"
  | "SHIPPED"
  | "OUT_FOR_DELIVERY"
  | "DELIVERED"
  | "CANCELLED"

export interface PaymentTerms {
  type: string
  collected_by: string
  currency: string
  status: string
  uri?: string | null
  transaction_id?: string | null
}

export interface CommitResult {
  transaction_id: string
  order_id: string
  order_state: OrderState | null
  payment_terms: PaymentTerms | null
  fulfillment_eta: string | null
  bpp_id: string
  bpp_uri: string
  contract_id: string | null
  reasoning_steps: ReasoningStep[]
  messages: string[]
  status: "live" | "mock"
}

export interface StatusSnapshot {
  transaction_id: string
  order_id: string
  state: OrderState
  fulfillment_eta: string | null
  tracking_url: string | null
  observed_at: string
  status: "live" | "mock"
}

// ── Auth ────────────────────────────────────────────────────────────────────

export type UserRole = "requester" | "approver" | "admin"

export interface StubUser {
  id: string
  name: string
  email: string
  role: UserRole
}
