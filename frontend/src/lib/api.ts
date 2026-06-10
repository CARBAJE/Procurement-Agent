import axios from "axios"
import type {
  AnalyticsData,
  AnalyticsPeriod,
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

export async function fetchBenchmark(): Promise<BenchmarkReport> {
  const { data } = await axios.get<BenchmarkReport>("/api/analytics/benchmark")
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

export interface DemoNegotiateOffer {
  provider_id: string
  item_id: string
  price: number
  currency?: string
  delivery_hours: number
  quantity: number
  score?: number
}

export interface DemoNegotiateRequest {
  transaction_id?: string
  category?: string
  ranked_offers: DemoNegotiateOffer[]
  policy?: Record<string, unknown>
  max_rounds?: number
  simulated_outcome?: "accepted" | "counter" | "escalate"
  callback_delay_s?: number
}

export interface DemoNegotiateAccepted {
  thread_id: string
  status: string
  paused_at: string | null
  interrupt: Record<string, unknown> | null
  final_outcome: string | null
  callback_delay_s: number
  simulated_outcome: string
}

export interface DemoNegotiateSnapshot {
  thread_id: string
  next: string[]
  final_outcome: string | null
  awaiting_on_select: boolean | null
  current_target: Record<string, unknown> | null
  current_counter_offer: Record<string, unknown> | null
  last_on_select_payload: Record<string, unknown> | null
  negotiation_round: number
  audit_event_count: number
  resumed: boolean
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

/** Kick off a real LangGraph negotiation session; returns 202 + thread_id. */
export async function kickoffNegotiation(
  payload: DemoNegotiateRequest,
): Promise<DemoNegotiateAccepted> {
  const { data } = await axios.post<DemoNegotiateAccepted>(
    "/api/demo/negotiate",
    payload,
  )
  return data
}

/** Poll the LangGraph state for a running negotiation. */
export async function pollNegotiation(
  threadId: string,
): Promise<DemoNegotiateSnapshot> {
  const { data } = await axios.get<DemoNegotiateSnapshot>(
    `/api/demo/negotiate/${encodeURIComponent(threadId)}`,
  )
  return data
}
