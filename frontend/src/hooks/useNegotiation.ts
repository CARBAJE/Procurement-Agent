"use client"

import { useCallback, useRef, useState } from "react"

import {
  kickoffNegotiation,
  pollNegotiation,
  supplierRespond,
  type DemoNegotiateRequest,
  type DemoNegotiateSnapshot,
} from "@/lib/api"

export type NegotiationStatus =
  | "idle"
  | "starting"
  | "buyer_thinking"
  | "supplier_thinking"
  | "done"
  | "error"

export interface UseNegotiation {
  status: NegotiationStatus
  snapshot: DemoNegotiateSnapshot | null
  error: string | null
  agreedPrice: number | null
  agreedDeliveryDate: string | null
  supplierModel: string | null
  /** Kick off a fully-autonomous buyer-vs-supplier negotiation. */
  start: (req: DemoNegotiateRequest) => Promise<void>
  /** Clear all state back to idle. */
  reset: () => void
}

const POLL_INTERVAL_MS = 600
const MAX_POLLS_PER_ROUND = 40

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Drives the real two-agent negotiation:
 *
 *   buyer (LangGraph engine, deterministic + guardrail-capped)
 *     ⇅ via the demo gateway + Redis
 *   supplier (qwen3:8b local LLM)
 *
 * After kickoff the buyer parks at `wait_for_async_callback`; the hook polls
 * until `awaiting_supplier`, then asks the supplier agent to respond (which
 * resumes the buyer for the next round), looping until the engine finalizes.
 */
export function useNegotiation(): UseNegotiation {
  const [status, setStatus] = useState<NegotiationStatus>("idle")
  const [snapshot, setSnapshot] = useState<DemoNegotiateSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [agreedPrice, setAgreedPrice] = useState<number | null>(null)
  const [agreedDeliveryDate, setAgreedDeliveryDate] = useState<string | null>(null)
  const [supplierModel, setSupplierModel] = useState<string | null>(null)

  // Guards against overlapping runs / state updates after reset.
  const runIdRef = useRef(0)

  const reset = useCallback(() => {
    runIdRef.current += 1
    setStatus("idle")
    setSnapshot(null)
    setError(null)
    setAgreedPrice(null)
    setAgreedDeliveryDate(null)
    setSupplierModel(null)
  }, [])

  const start = useCallback(async (req: DemoNegotiateRequest) => {
    const runId = ++runIdRef.current
    const alive = () => runIdRef.current === runId

    setStatus("starting")
    setSnapshot(null)
    setError(null)
    setAgreedPrice(null)
    setAgreedDeliveryDate(null)
    setSupplierModel(null)

    try {
      const accepted = await kickoffNegotiation(req)
      if (!alive()) return
      const threadId = accepted.thread_id
      const maxRounds = accepted.max_rounds

      // Drive up to maxRounds + 1 supplier turns (the engine finalizes well
      // within this; the cap is a safety backstop).
      for (let turn = 0; turn <= maxRounds; turn += 1) {
        // 1) Poll until the buyer has parked awaiting a supplier reply.
        let snap: DemoNegotiateSnapshot | null = null
        for (let i = 0; i < MAX_POLLS_PER_ROUND; i += 1) {
          if (!alive()) return
          snap = await pollNegotiation(threadId)
          setSnapshot(snap)
          if (snap.final_outcome || snap.awaiting_supplier) break
          await sleep(POLL_INTERVAL_MS)
        }
        if (!alive() || !snap) return

        if (snap.final_outcome) {
          setStatus("done")
          return
        }

        // 2) Ask the qwen3 supplier to respond → resumes the buyer graph.
        setStatus("supplier_thinking")
        const result = await supplierRespond(threadId)
        if (!alive()) return
        if (result.model) setSupplierModel(result.model)

        if (result.done) {
          if (typeof result.agreed_price === "number") {
            setAgreedPrice(result.agreed_price)
          }
          if (result.agreed_delivery_date) {
            setAgreedDeliveryDate(result.agreed_delivery_date)
          }
          // Final poll so the history/round reflect the closed deal.
          const finalSnap = await pollNegotiation(threadId)
          if (!alive()) return
          setSnapshot(finalSnap)
          if (finalSnap.agreed_delivery_date) {
            setAgreedDeliveryDate(finalSnap.agreed_delivery_date)
          }
          setStatus("done")
          return
        }

        // 3) Buyer is computing its next counter-offer.
        setStatus("buyer_thinking")
        await sleep(POLL_INTERVAL_MS)
      }

      // Safety: loop exhausted without an explicit terminal signal.
      if (alive()) setStatus("done")
    } catch (err) {
      if (!alive()) return
      const response = (
        err as { response?: { status?: number; data?: { detail?: string; error?: string } } }
      )?.response
      const fromServer = response?.data?.detail ?? response?.data?.error
      let message: string
      if (fromServer) {
        message = fromServer
      } else if (!response) {
        message = "Unable to reach the negotiation service. Please check your connection and try again."
      } else if (response.status === 404) {
        message = "Negotiation session not found. Please go back and start a new one from the compare page."
      } else {
        message = "Negotiation failed. Please try again."
      }
      setError(message)
      setStatus("error")
    }
  }, [])

  return {
    status,
    snapshot,
    error,
    agreedPrice,
    agreedDeliveryDate,
    supplierModel,
    start,
    reset,
  }
}
