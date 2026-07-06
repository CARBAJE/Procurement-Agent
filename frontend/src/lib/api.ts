import axios from "axios"
import type {
  AnalyticsData,
  AnalyticsPeriod,
  AuditTrailResponse,
  BecknIntent,
  BenchmarkReport,
  CommitResult,
  ComparisonResult,
  OrderDetail,
  ParseResult,
  StatusSnapshot,
} from "@/lib/types"

// ── /parse — NL → BecknIntent via IntentParser ──────────────────────────────

export async function parseIntent(query: string): Promise<ParseResult> {
  const { data } = await axios.post<ParseResult>("/api/procurement/parse", { query })
  return data
}

// ── /compare — run discover + rank, return offerings + scoring ──────────────

export async function compareOfferings(
  intent: BecknIntent,
  rawQuery?: string,
): Promise<ComparisonResult> {
  const body = rawQuery ? { ...intent, raw_query: rawQuery } : intent
  const { data } = await axios.post<ComparisonResult>("/api/procurement/compare", body)
  return data
}

// ── /commit — user confirms a chosen offering, runs select+init+confirm ────

export async function commitOrder(
  transactionId: string,
  chosenItemId: string,
): Promise<CommitResult> {
  const { data } = await axios.post<CommitResult>("/api/procurement/commit", {
    transaction_id: transactionId,
    chosen_item_id: chosenItemId,
  })
  return data
}

// ── /analytics — dashboard KPIs and trends ──────────────────────────────────

export async function fetchAnalytics(period: AnalyticsPeriod = "90d"): Promise<AnalyticsData> {
  const { data } = await axios.get<AnalyticsData>(`/api/analytics?period=${period}`)
  return data
}

// ── /analytics/benchmark — CPO benchmarking report ──────────────────────────

export async function fetchBenchmark(period: AnalyticsPeriod = "90d"): Promise<BenchmarkReport> {
  const { data } = await axios.get<BenchmarkReport>(`/api/analytics/benchmark?period=${period}`)
  return data
}

// ── /analytics/business-impact — live actuals for Business Impact cards ─────

export interface BusinessImpactLive {
  monthly_savings: number
  requests_this_month: number
  avg_cycle_time_hours: number
  data_source: "live"
}

export async function fetchBusinessImpact(period: AnalyticsPeriod = "90d"): Promise<BusinessImpactLive> {
  const { data } = await axios.get<BusinessImpactLive>(`/api/analytics/business-impact?period=${period}`)
  return data
}

// ── /cancel — mark procurement request as cancelled ─────────────────────────

export async function cancelRequest(requestId: string): Promise<void> {
  await axios.patch("/api/procurement/cancel", { request_id: requestId })
}

// ── /status — poll order lifecycle ──────────────────────────────────────────

export async function getOrderStatus(
  transactionId: string,
  orderId: string,
  bppId?: string,
  bppUri?: string,
): Promise<StatusSnapshot> {
  const params = new URLSearchParams()
  if (bppId)  params.set("bpp_id", bppId)
  if (bppUri) params.set("bpp_uri", bppUri)
  const suffix = params.toString() ? `?${params.toString()}` : ""
  const { data } = await axios.get<StatusSnapshot>(
    `/api/procurement/status/${encodeURIComponent(transactionId)}/${encodeURIComponent(orderId)}${suffix}`,
  )
  return data
}

// ── /order/{id} — DB-backed order detail (view past orders, no session) ─────

export async function getOrderDetail(id: string): Promise<OrderDetail> {
  const { data } = await axios.get<OrderDetail>(
    `/api/procurement/order/${encodeURIComponent(id)}`,
  )
  return data
}

// ── /audit — audit trail for a request ──────────────────────────────────────

export async function getAuditEvents(
  requestId: string,
  limit = 100,
): Promise<AuditTrailResponse> {
  const { data } = await axios.get<AuditTrailResponse>(
    `/api/audit?request_id=${encodeURIComponent(requestId)}&limit=${limit}`,
  )
  return data
}

// ── Demo Gateway ────────────────────────────────────────────────────────────
//
// These functions hit the Python "Dynamic Mock Gateway" (services/
// frontend_demo_gateway/) via Next.js proxy routes under /api/demo/*. The
// gateway runs the *real* Phase-2 PyTorch ranker and the *real* Phase-3
// LangGraph state machine — only the external infrastructure (MLflow,
// Postgres, Redis, Kafka, live Beckn networks) is replaced with fast
// deterministic simulators. Use these instead of the static JSON mocks
// when showcasing the production sorting and negotiation behaviour.

export interface DemoScoreSupplier {
  id: string
  supplier_name?: string
  price: number
  delivery_time_hours: number
  risk_score?: number
}

export interface DemoRankedSupplier extends DemoScoreSupplier {
  rank: number
  score: number
  features: { price: number; speed: number; risk: number }
}

export interface DemoScoreResponse {
  transaction_id: string | null
  recommended_id: string
  ranked: DemoRankedSupplier[]
  model_version: string
  model_weights: { w_price: number; w_speed: number; w_risk: number; bias: number }
  latency_ms: number
  pipeline: string
}

/** Demo kickoff payload — buyer's deal parameters for the negotiation. */
export interface DemoNegotiateRequest {
  supplier_id?: string
  supplier_name?: string
  item: string
  quantity: number
  target_price: number
  list_price?: number
  delivery_hours?: number
  /** Buyer's desired delivery date (ISO yyyy-mm-dd). */
  requested_delivery_date?: string
  category?: string
  max_rounds?: number
}

/** A drafted counter-offer the buyer (LangGraph) parks on. */
export interface BuyerCounterOffer {
  target_price: number
  target_delivery_hours?: number
  target_quantity?: number
  discount_pct: number
  rationale?: string
}

/** 202 result from kicking off a negotiation against the live engine. */
export interface DemoNegotiateAccepted {
  thread_id: string
  status: string
  paused_at: string | null
  buyer_counter_offer: BuyerCounterOffer | null
  list_price: number
  target_price: number
  requested_delivery_date: string
  max_rounds: number
}

/** One full negotiation round — both the buyer's message and the supplier's reply. */
export interface NegotiationHistoryTurn {
  round_no: number
  // Buyer side (full message)
  buyer_price_offer: number
  buyer_delivery_offer: string
  buyer_quantity: number
  buyer_justification: string
  // Supplier side (qwen3:8b)
  supplier_action: "accept" | "counter" | "reject"
  supplier_price: number | null
  proposed_delivery_date: string | null
  supplier_message: string
  source: "llm" | "fallback"
  resume_status: "accepted" | "counter"
}

/** Snapshot merging the buyer graph state + gateway session. */
export interface DemoNegotiateSnapshot {
  thread_id: string
  negotiation_round: number
  rounds_elapsed: number
  max_rounds: number
  awaiting_supplier: boolean
  final_outcome: string | null
  buyer_counter_offer: BuyerCounterOffer | null
  list_price: number
  target_price: number
  requested_delivery_date: string
  agreed_delivery_date: string | null
  item: string
  history: NegotiationHistoryTurn[]
}

/** The qwen3:8b supplier's reply to the buyer's current counter-offer. */
export interface SupplierTurn {
  action: "accept" | "counter" | "reject"
  counter_price: number | null
  proposed_delivery_date: string | null
  message: string
  model: string
  source: "llm" | "fallback"
}

/** Result of asking the supplier agent to respond this round. */
export interface SupplierRespondResult {
  done: boolean
  round_no?: number
  buyer_ask?: number
  supplier?: SupplierTurn
  agreed_price?: number | null
  agreed_delivery_date?: string | null
  resume_status?: "accepted" | "counter"
  model?: string
  final_outcome?: string
}

/** Run the real Phase-2 LTR ranker against a list of candidate suppliers. */
export async function scoreSuppliers(
  items: DemoScoreSupplier[],
  transactionId?: string,
): Promise<DemoScoreResponse> {
  const { data } = await axios.post<DemoScoreResponse>("/api/demo/score", {
    items,
    transaction_id: transactionId,
  })
  return data
}

/** Kick off a real LangGraph negotiation against the live engine (202). */
export async function kickoffNegotiation(
  payload: DemoNegotiateRequest,
): Promise<DemoNegotiateAccepted> {
  const { data } = await axios.post<DemoNegotiateAccepted>(
    "/api/demo/negotiate",
    payload,
  )
  return data
}

/** Poll the buyer-graph + session state for a running negotiation. */
export async function pollNegotiation(
  threadId: string,
): Promise<DemoNegotiateSnapshot> {
  const { data } = await axios.get<DemoNegotiateSnapshot>(
    `/api/demo/negotiate/${encodeURIComponent(threadId)}`,
  )
  return data
}

/** Ask the qwen3:8b supplier agent to respond to the buyer's current offer. */
export async function supplierRespond(
  threadId: string,
): Promise<SupplierRespondResult> {
  const { data } = await axios.post<SupplierRespondResult>(
    `/api/demo/negotiate/${encodeURIComponent(threadId)}/supplier-respond`,
  )
  return data
}
