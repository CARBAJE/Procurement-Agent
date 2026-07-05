"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  AlertCircle, ArrowLeft, Clock, Handshake, Hash,
  Loader2, Send, ShieldAlert, ThumbsDown, ThumbsUp,
  XCircle, Info,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import ComparisonTable from "@/components/procurement/ComparisonTable"
import ScoringPanel    from "@/components/procurement/ScoringPanel"
import ReasoningPanel  from "@/components/procurement/ReasoningPanel"
import { decideRun, getRun } from "@/lib/api"
import { loadRunSession, loadSession, saveRunSession, saveSession } from "@/lib/session-store"
import type { BecknIntent, ComparisonResult, PolicyDecision, RunResult } from "@/lib/types"
import axios from "axios"

interface RunViewProps {
  runId: string
}

function extractError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && err.response?.data) {
    const d = err.response.data as { error?: string; detail?: string }
    return d.error ?? d.detail ?? fallback
  }
  return fallback
}

// ── Policy explanation strip ─────────────────────────────────────────────────

function PolicyExplanationCard({ decision }: { decision: PolicyDecision }) {
  if (!decision.explanation && !decision.flags.length) return null
  return (
    <Card className="border-blue-200 bg-blue-50/40">
      <CardContent className="pt-4 pb-3">
        <div className="flex items-start gap-2">
          <Info className="h-4 w-4 text-blue-500 mt-0.5 shrink-0" aria-hidden="true" />
          <div className="space-y-1.5">
            {decision.explanation && (
              <p className="text-sm text-blue-900">{decision.explanation}</p>
            )}
            {decision.erp_fallback && (
              <p className="text-xs text-blue-700">
                ERP policy unavailable — base policy applied.
              </p>
            )}
            {decision.flags.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {decision.flags.map((f) => (
                  <Badge key={f} variant="outline" className="text-[10px] border-blue-300 text-blue-700">
                    {f.replace(/_/g, " ")}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── RBAC pending card ─────────────────────────────────────────────────────────

function RbacPendingCard({ run }: { run: RunResult }) {
  const router = useRouter()
  return (
    <Card className="border-amber-500/40 bg-amber-50/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-amber-800">
          <Clock className="h-5 w-5 shrink-0" aria-hidden="true" />
          Order Submitted for Approval
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-amber-900">
        {run.amount_total != null && (
          <p>
            Order total of{" "}
            <strong>
              ₹{run.amount_total.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </strong>{" "}
            exceeds the auto-approval threshold and has been routed to an approver.
          </p>
        )}
        {run.explanation && <p className="text-xs text-amber-800">{run.explanation}</p>}
        <p className="text-xs text-amber-700">
          Request ID: <span className="font-mono">{run.request_id}</span>
        </p>
        <Button variant="outline" size="sm" onClick={() => router.push("/request/new")}>
          Start a new request
        </Button>
      </CardContent>
    </Card>
  )
}

// ── Main RunView ──────────────────────────────────────────────────────────────

export default function RunView({ runId }: RunViewProps) {
  const router = useRouter()

  const [run,        setRun]        = useState<RunResult | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState("")

  // Redirect to the full order page whenever the run reaches the confirmed stage.
  // For autonomous mode, also write a WizardSession keyed by request_id so the
  // order page (OrderView path 1) can display negotiated price info without a DB
  // round-trip.
  useEffect(() => {
    if (run?.stage !== "confirmed" || !run.request_id) return

    // Build a WizardSession only when the confirmed result carries offering data
    // (autonomous mode). Advisory/HITL sessions are written earlier in the flow.
    const offerings = run.offerings ?? []
    const chosenItemId = run.decision?.final_item_id ?? run.recommended_item_id ?? null
    const chosenOffer = offerings.find((o) => o.item_id === chosenItemId)
    if (offerings.length > 0 && chosenOffer && !loadSession(run.request_id)) {
      const commit = {
        transaction_id:  run.transaction_id,
        request_id:      run.request_id,
        order_id:        run.order_id ?? null,
        order_state:     run.order_state ?? null,
        payment_terms:   run.payment_terms ?? null,
        fulfillment_eta: null,
        bpp_id:          run.bpp_id ?? "",
        bpp_uri:         run.bpp_uri ?? "",
        contract_id:     run.contract_id ?? null,
        reasoning_steps: run.reasoning_steps ?? [],
        messages:        run.messages ?? [],
        status:          run.status ?? "live",
      }
      const negotiation =
        run.negotiation_settled_price != null && run.negotiation_settled_price > 0
          ? { settled_price: run.negotiation_settled_price, agreed_delivery_date: null }
          : null
      saveSession(run.request_id, {
        intent:      { quantity: chosenOffer.available_quantity ?? 1 } as BecknIntent,
        comparison:  {
          transaction_id:      run.transaction_id,
          request_id:          run.request_id,
          offerings,
          recommended_item_id: chosenItemId,
          scoring:             run.scoring ?? { recommended_item_id: null, criteria: [], ranking: [] },
          reasoning_steps:     run.reasoning_steps ?? [],
          messages:            run.messages ?? [],
          status:              "live",
        } as ComparisonResult,
        chosenItemId,
        commit,
        negotiation,
      })
    }

    router.push(`/request/${encodeURIComponent(run.request_id)}/order`)
  }, [run, router])

  // Load from sessionStorage first; fall back to API fetch.
  useEffect(() => {
    const cached = loadRunSession(runId)
    if (cached) {
      setRun(cached)
      setSelectedId(cached.recommended_item_id ?? null)
      setLoading(false)
    } else {
      getRun(runId)
        .then((data) => {
          setRun(data)
          setSelectedId(data.recommended_item_id ?? null)
          saveRunSession(runId, data)
        })
        .catch(() => setError("Unable to load this run. It may have expired."))
        .finally(() => setLoading(false))
    }
  }, [runId])

  async function handleProceed() {
    if (!run) return
    const stage = run.stage
    if (stage === "awaiting_selection" && !selectedId) return
    setSubmitting(true)
    setError("")
    try {
      // For HITL approval: if the user negotiated before approving, read the
      // settled price from the bridge WizardSession and forward it so the
      // backend commits at the negotiated price instead of the original quote.
      let negotiatedPrice: number | undefined
      if (stage === "awaiting_approval") {
        const bridgeSession = loadSession(run.transaction_id)
        const settled = bridgeSession?.negotiation?.settled_price
        if (settled != null && settled > 0) negotiatedPrice = settled
      }

      const result = await decideRun(
        runId,
        "proceed",
        stage === "awaiting_selection" ? (selectedId ?? undefined) : undefined,
        negotiatedPrice,
      )
      saveRunSession(runId, result)
      setRun(result)
      setSelectedId(result.recommended_item_id ?? selectedId)
    } catch (err) {
      setError(extractError(err, "Unable to proceed. Please try again."))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReject() {
    if (!run) return
    setSubmitting(true)
    setError("")
    try {
      const result = await decideRun(runId, "reject")
      saveRunSession(runId, result)
      setRun(result)
      // After HITL rejection the stage becomes awaiting_selection;
      // pre-select the recommended item so the table has a default.
      setSelectedId(result.recommended_item_id ?? null)
    } catch (err) {
      setError(extractError(err, "Unable to reject. Please try again."))
    } finally {
      setSubmitting(false)
    }
  }

  // ── Loading ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Loading procurement run">
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2"><Skeleton className="h-64 w-full" /></div>
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    )
  }

  // ── Error / not found ──────────────────────────────────────────────────────
  if (!run) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-destructive" aria-hidden="true" />
            Run unavailable
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {error || "This run could not be loaded. It may have expired or been opened in a different tab."}
          </p>
          <Button onClick={() => router.push("/request/new")}>Start a new request</Button>
        </CardContent>
      </Card>
    )
  }

  // ── Terminal stages ────────────────────────────────────────────────────────
  // "confirmed" is handled by the redirect useEffect above — render nothing while navigating.
  if (run.stage === "confirmed") return null
  if (run.stage === "awaiting_rbac_approval") return <RbacPendingCard run={run} />

  if (run.stage === "no_offerings") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
            No suppliers found
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            No suppliers responded for this request. Try adjusting the item, quantity,
            or delivery window and search again.
          </p>
          <Button onClick={() => router.push("/request/new")}>Search again</Button>
        </CardContent>
      </Card>
    )
  }

  if (run.stage === "rejected") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
            Request cancelled
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            This procurement request was cancelled.
          </p>
          <Button onClick={() => router.push("/request/new")}>Start a new request</Button>
        </CardContent>
      </Card>
    )
  }

  // ── Interactive stages: awaiting_selection | awaiting_approval ─────────────
  const offerings         = run.offerings ?? []
  const scoring           = run.scoring
  const decision          = run.decision
  const recommendedItemId = decision?.final_item_id ?? run.recommended_item_id ?? null
  const isSelection       = run.stage === "awaiting_selection"
  const isApproval        = run.stage === "awaiting_approval"

  const stageLabel = isSelection ? "Select a Supplier" : "Review Agent Recommendation"
  const breadcrumb = isSelection
    ? "Request → Find suppliers → Select"
    : "Request → Find suppliers → Approve recommendation"

  const proceedLabel = isApproval ? "Approve recommendation" : "Proceed with selection"
  const canProceed   = isApproval || (isSelection && !!selectedId)

  function goNegotiate() {
    if (!run || !selectedId) return
    const offer = offerings.find((o) => o.item_id === selectedId)
    if (!offer) return

    // Write a WizardSession bridge so NegotiateView.patchSession works on
    // completion, and OrderView path 1 can display the confirmed order without
    // a DB round-trip (advisory) or so RunView can read negotiated terms back
    // after HITL returns from the negotiate page.
    saveSession(run.transaction_id, {
      intent:      { quantity: offer.available_quantity ?? 1 } as BecknIntent,
      comparison:  {
        transaction_id:      run.transaction_id,
        request_id:          run.request_id,
        offerings,
        recommended_item_id: recommendedItemId,
        scoring:             run.scoring ?? { recommended_item_id: null, criteria: [], ranking: [] },
        reasoning_steps:     run.reasoning_steps ?? [],
        messages:            run.messages ?? [],
        status:              "live",
      } as ComparisonResult,
      chosenItemId: selectedId,
      commit: null,
    })

    const listPrice = parseFloat(offer.price_value)
    const hours = offer.fulfillment_hours ?? 336
    const deliveryDate = new Date(Date.now() + hours * 3_600_000).toISOString().slice(0, 10)
    const qty = offer.available_quantity ?? 1
    const params = new URLSearchParams({
      supplier_id:    offer.provider_id,
      item_id:        offer.item_id,
      original_price: String(Number.isFinite(listPrice) ? listPrice : 0),
      delivery_date:  deliveryDate,
      item:           offer.item_name,
      quantity:       String(qty),
    })

    // HITL: after negotiation the user must still explicitly approve, so we
    // signal NegotiateView to return here rather than commit immediately.
    if (isApproval) {
      params.set("return_to", `/request/${encodeURIComponent(run.run_id)}/run`)
    }

    router.push(`/request/${encodeURIComponent(run.transaction_id)}/negotiate?${params.toString()}`)
  }

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div>
        <p className="text-xs text-muted-foreground mb-1">{breadcrumb}</p>
        <h1 className="text-4xl font-extrabold tracking-tight">{stageLabel}</h1>
        <div className="flex items-center gap-1.5 mt-1">
          <Hash className="h-3 w-3 text-muted-foreground" />
          <span className="text-xs text-muted-foreground font-mono">{run.run_id}</span>
        </div>
      </div>

      {/* ── Policy explanation (hitl approval stage) ───────────────────────── */}
      {isApproval && decision && <PolicyExplanationCard decision={decision} />}

      {/* ── Approving on the recommended item vs selection ──────────────────── */}
      {isApproval && recommendedItemId && (
        <div className="flex items-center gap-2">
          <span className="h-4 w-0.5 rounded-full bg-primary shrink-0" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Agent recommendation</h2>
          <Badge variant="secondary" className="text-xs">
            {decision?.final_provider_name ?? recommendedItemId}
          </Badge>
          {decision?.flags.includes("PREFERRED_SUPPLIER_APPLIED") && (
            <Badge variant="outline" className="text-xs text-blue-700 border-blue-300">
              ERP preferred
            </Badge>
          )}
        </div>
      )}

      {/* ── Table + scoring ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-3 min-w-0">
          {isSelection && (
            <div className="flex items-center gap-2">
              <span className="h-4 w-0.5 rounded-full bg-primary shrink-0" aria-hidden="true" />
              <h2 className="text-sm font-semibold">{offerings.length} Offerings</h2>
              <span className="text-xs text-muted-foreground">— select a row to choose</span>
            </div>
          )}
          <ComparisonTable
            offerings={offerings}
            recommendedItemId={recommendedItemId}
            selectedItemId={isApproval ? recommendedItemId : selectedId}
            onSelect={isApproval ? () => {} : setSelectedId}
          />
        </div>
        {scoring && (
          <div>
            <ScoringPanel
              scoring={scoring}
              offerings={offerings}
              selectedItemId={isApproval ? recommendedItemId : selectedId}
            />
          </div>
        )}
      </div>

      {/* ── Action bar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between pt-2 border-t flex-wrap gap-3">
        <Button
          variant="outline"
          onClick={() => router.push("/request/new")}
          disabled={submitting}
        >
          <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
          Cancel
        </Button>

        <div className="flex items-center gap-3 flex-wrap">
          {isApproval && (
            <Button
              variant="outline"
              onClick={handleReject}
              disabled={submitting}
              aria-label="Reject the agent's recommendation and choose manually"
            >
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ThumbsDown className="mr-2 h-4 w-4" aria-hidden="true" />
              )}
              Review other suppliers
            </Button>
          )}

          {isApproval && decision?.requires_negotiation && (
            <Button
              variant="outline"
              disabled={submitting}
              onClick={goNegotiate}
              aria-label="Negotiate terms before approving this recommendation"
            >
              <Handshake className="mr-2 h-4 w-4" aria-hidden="true" />
              Negotiate first
            </Button>
          )}

          {isSelection && (
            <Button
              variant="outline"
              disabled={!selectedId || submitting}
              onClick={goNegotiate}
              aria-label="Negotiate terms with the selected supplier"
            >
              <Handshake className="mr-2 h-4 w-4" aria-hidden="true" />
              Negotiate Terms
            </Button>
          )}

          <Button
            onClick={handleProceed}
            disabled={!canProceed || submitting}
            aria-busy={submitting}
          >
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                {isApproval ? "Approving…" : "Placing order…"}
              </>
            ) : isApproval ? (
              <>
                <ThumbsUp className="mr-2 h-4 w-4" aria-hidden="true" />
                {proceedLabel}
              </>
            ) : (
              <>
                <Send className="mr-2 h-4 w-4" aria-hidden="true" />
                {proceedLabel}
              </>
            )}
          </Button>
        </div>
      </div>

      {submitting && !error && (
        <p role="status" className="text-xs text-muted-foreground text-right">
          Placing order through the Beckn network — this may take a few seconds.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive text-right">
          <ShieldAlert className="inline h-4 w-4 mr-1" aria-hidden="true" />
          {error}
        </p>
      )}

      {/* ── Reasoning trace ───────────────────────────────────────────────── */}
      {(run.reasoning_steps?.length ?? 0) > 0 && (
        <ReasoningPanel
          steps={run.reasoning_steps ?? []}
          messages={run.messages ?? []}
        />
      )}
    </div>
  )
}
