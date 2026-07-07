// Mirrors Bap-1/src/beckn/models.py and IntentParser/schemas.py
export interface BudgetConstraints {
  max: number | null
  min?: number | null
}

export interface BecknIntent {
  item: string
  descriptions: string[]
  quantity: number
  unit: string
  location_coordinates: string  // "lat,lon"
  // Nullable: a minimal query (e.g. just "Laptop") leaves these unspecified.
  delivery_timeline: number | null   // hours
  budget_constraints: BudgetConstraints | null
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
  request_id: string
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
  request_id: string
  order_id: string | null
  order_state: OrderState | null
  payment_terms: PaymentTerms | null
  fulfillment_eta: string | null
  bpp_id: string
  bpp_uri: string
  contract_id: string | null
  reasoning_steps: ReasoningStep[]
  messages: string[]
  /** "pending_approval" is returned as HTTP 202 when order_total > user threshold. */
  status: "live" | "mock" | "pending_approval"
  /** Set only when status === "pending_approval". */
  amount_total?: number
}

// ── Approval workflow ────────────────────────────────────────────────────────

export interface PendingApprovalItem {
  request_id: string
  transaction_id: string
  chosen_item_id: string
  actor: { keycloak_id: string; email: string; name: string; role: string }
  amount_total: number
  item_description: string
  provider_name: string
  created_at: string
}

// ── Admin ────────────────────────────────────────────────────────────────────

export interface AdminUser {
  user_id: string
  email: string
  name: string
  role: UserRole
  department: string
  approval_threshold: number
  budget_remaining: number
  keycloak_id: string
  idp_provider: string
  created_at: string
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

// ── /order/{request_id} — DB-backed order detail (no session needed) ─────────

export interface OrderDetailOrder {
  order_id: string
  order_state: OrderState
  fulfillment_eta: string | null
  bpp_id: string
  bpp_uri: string
  status: "live" | "mock"
  quantity: number
  offering: Offering
  // Enriched by the orchestrator when the in-memory order cache is still alive.
  payment_terms?: PaymentTerms | null
  contract_id?: string | null
  reasoning_steps?: ReasoningStep[]
  messages?: string[]
}

export interface OrderDetail {
  found: boolean
  request_id: string
  raw_input_text: string
  request_status: string
  category: string | null
  created_at: string | null
  intent: BecknIntent | null
  order: OrderDetailOrder | null
}

// ── Analytics Dashboard ──────────────────────────────────────────────────────

export interface KpiMetrics {
  total_spend: number
  total_savings: number
  savings_percent: number
  active_requests: number
  completed_this_month: number
  pending_approval: number
  avg_cycle_time_hours: number
  baseline_cycle_time_hours: number
  active_suppliers: number
}

export interface SpendDataPoint {
  date: string
  spend: number
  savings: number
}

export interface CycleTimeCategory {
  category: string
  before_hours: number
  after_hours: number
}

export interface SpendByCategory {
  category: string
  spend: number
}

export interface NegotiationSaving {
  category: string
  avg_discount_percent: number
  total_savings: number
}

export interface RequestVolumePoint {
  date: string
  count: number
}

export interface StatusCount {
  status: string
  count: number
}

export interface AcceptancePoint {
  date: string
  accepted_pct: number
  total: number
  overridden_count: number
}

export interface SupplierMetric {
  bpp_id: string
  provider_name: string
  quality_score: number
  delivery_score: number
  price_competitiveness: number
  compliance_score: number
  total_orders: number
}

export interface AnalyticsRequest {
  request_id: string
  raw_input_text: string
  status: string
  category: string | null
  agreed_price: number | null
  quantity?: number | null
  currency: string
  created_at: string
  user_overridden: boolean | null
}

export interface AnalyticsData {
  kpis: KpiMetrics
  spend_over_time: SpendDataPoint[]
  spend_by_category: SpendByCategory[]
  negotiation_savings: NegotiationSaving[]
  request_volume: RequestVolumePoint[]
  cycle_time_by_category: CycleTimeCategory[]
  status_funnel: StatusCount[]
  acceptance_rate: AcceptancePoint[]
  supplier_metrics: SupplierMetric[]
  recent_requests: AnalyticsRequest[]
  period: string
  data_source: "live" | "mock"
}

export type AnalyticsPeriod = "30d" | "90d" | "180d"

// ── Business Impact ──────────────────────────────────────────────────────────

export interface BusinessImpact {
  platform_licensing: { baseline_monthly: number; actual_monthly: number }
  team_productivity:  { requests_per_fte_before: number; requests_per_fte_after: number }
  audit_prep_hours:   { before: number; after: number }
}

// ── CPO Benchmarking ─────────────────────────────────────────────────────────

export interface BenchmarkCategory {
  category: string
  current_contract: number
  best_market_price: number
  gap_percent: number
  annual_savings: number
  top_alternative: string
}

export interface BenchmarkReport {
  generated_at: string
  projected_annual_savings: number
  categories: BenchmarkCategory[]
}

// ── /run — orchestrated procurement state machine ────────────────────────────

export type ExecutionMode = "advisory" | "hitl" | "autonomous"

export type RunStage =
  | "awaiting_selection"      // advisory: user picks from table
  | "awaiting_approval"       // hitl: user approves agent's recommendation
  | "awaiting_rbac_approval"  // amount > threshold; sent to approver queue
  | "auto_commit"             // autonomous (transient, transitions to confirmed)
  | "confirmed"               // order committed
  | "rejected"                // run cancelled
  | "no_offerings"            // discovery returned empty

export interface PolicyRule {
  rule_id: string
  source: string
  applied: boolean
  input_summary: string
  outcome: string
}

export interface PolicyDecision {
  ml_item_id: string | null
  ml_provider_name: string | null
  final_item_id: string | null
  final_provider_name: string | null
  next_stage: RunStage
  policy: {
    selection_required: boolean
    approval_required: boolean
    auto_commit: boolean
  }
  rules_applied: PolicyRule[]
  explanation: string
  flags: string[]
  erp_fallback: boolean
  requires_negotiation?: boolean
}

export interface RunResult {
  run_id: string
  transaction_id: string
  request_id: string
  stage: RunStage
  execution_mode?: ExecutionMode
  offerings?: Offering[]
  recommended_item_id?: string | null
  scoring?: Scoring
  reasoning_steps?: ReasoningStep[]
  messages?: string[]
  decision?: PolicyDecision
  // confirmed path
  order_id?: string | null
  order_state?: OrderState | null
  payment_terms?: PaymentTerms | null
  contract_id?: string | null
  bpp_id?: string
  bpp_uri?: string
  status?: "live" | "mock"
  // awaiting_rbac_approval / awaiting_selection after rejection
  amount_total?: number
  explanation?: string
  message?: string
  // autonomous confirmed: settled price after negotiation (null = no deal / not attempted)
  negotiation_settled_price?: number | null
}

// ── Audit Trail ─────────────────────────────────────────────────────────────

export type AuditEventType =
  | "discover" | "normalize" | "score" | "negotiate"
  | "approve"  | "confirm"  | "override" | "erp_sync" | "notification"

export interface AuditEvent {
  event_id:          string
  request_id:        string | null
  po_id:             string | null
  actor_id:          string | null
  event_type:        AuditEventType
  agent_action:      string
  reasoning_payload: Record<string, unknown>
  kafka_offset:      number
  splunk_indexed:    boolean
  event_timestamp:   string
  retention_until:   string
}

export interface AuditTrailResponse {
  count:  number
  events: AuditEvent[]
}

// ── Auth ────────────────────────────────────────────────────────────────────

export type UserRole = "requester" | "approver" | "admin"
