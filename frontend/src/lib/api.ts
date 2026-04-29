import axios from "axios"
import type {
  BecknIntent,
  CommitResult,
  ComparisonResult,
  ParseResult,
  StatusSnapshot,
} from "@/lib/types"

// ── /parse — NL → BecknIntent via IntentParser ──────────────────────────────

export async function parseIntent(query: string): Promise<ParseResult> {
  const { data } = await axios.post<ParseResult>("/api/procurement/parse", { query })
  return data
}

// ── /compare — run discover + rank, return offerings + scoring ──────────────

export async function compareOfferings(intent: BecknIntent): Promise<ComparisonResult> {
  const { data } = await axios.post<ComparisonResult>("/api/procurement/compare", intent)
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
