"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
  AlertCircle, ArrowLeft, Clock, Handshake, Hash,
  Loader2, Send, ShieldAlert, Sparkles, ThumbsDown, ThumbsUp,
  XCircle, Info,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import ComparisonTable from "@/components/procurement/ComparisonTable"
import ScoringPanel    from "@/components/procurement/ScoringPanel"
import ReasoningPanel  from "@/components/procurement/ReasoningPanel"
import { cancelRequest, decideRun, explainSelection, getRun } from "@/lib/api"
import { loadRunSession, loadSession, saveRunSession, saveSession } from "@/lib/session-store"
import { useNavigationGuard } from "@/hooks/useNavigationGuard"
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

// ── Agent selection explanation ───────────────────────────────────────────────

function SelectionExplanationCard({
  run,
  recommendedItemId,
}: {
  run: RunResult
  recommendedItemId: string | null
}) {
  const [llmText,    setLlmText]    = useState<string | null>(null)
  const [llmLoading, setLlmLoading] = useState(false)
  const [llmError,   setLlmError]   = useState(false)
  const called = useRef(false)

  const rankingEntry = run.scoring?.ranking?.find((r) => r.item_id === recommendedItemId)

  const providerName =
    run.decision?.final_provider_name ??
    run.offerings?.find((o) => o.item_id === recommendedItemId)?.provider_name ??
    null

  const rankAndSelectStep = run.reasoning_steps?.find((s) => s.node === "rank_and_select")

  useEffect(() => {
    if (!recommendedItemId || called.current) return
    called.current = true

    // Build one entry per offering with ALL its criterion scores — gives the LLM
    // full cross-offering comparison data instead of just the winner's aggregate.
    const offerings = (run.offerings ?? []).map((o) => {
      const rankEntry = run.scoring?.ranking?.find((r) => r.item_id === o.item_id)
      const scoreDetails = (run.scoring?.criteria ?? []).flatMap((criterion) => {
        const row = criterion.scores.find((s) => s.item_id === o.item_id)
        if (!row) return []
        return [{
          criterion:   criterion.label,
          raw:         row.raw,
          normalized:  row.normalized,
          explanation: row.explanation,
        }]
      })
      return {
        provider:        o.provider_name,
        item:            o.item_name,
        price:           parseFloat(o.price_value) || 0,
        currency:        o.price_currency ?? "INR",
        delivery_hours:  o.fulfillment_hours ?? null,
        composite_score: rankEntry?.composite_score ?? null,
        rank:            rankEntry?.rank ?? null,
        is_recommended:  o.item_id === recommendedItemId,
        score_details:   scoreDetails,
      }
    })

    setLlmLoading(true)
    setLlmError(false)
    explainSelection({
      offerings,
      recommended_provider:      providerName ?? "",
      rank_and_select_summary:   rankAndSelectStep?.summary ?? null,
    })
      .then((res) => {
        if (res.explanation) setLlmText(res.explanation)
        else setLlmError(true)
      })
      .catch(() => setLlmError(true))
      .finally(() => setLlmLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recommendedItemId])

  if (!recommendedItemId) return null

  return (
    <Card className="border-emerald-200 bg-emerald-50/30">
      <CardContent className="pt-4 pb-4">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-emerald-100 text-emerald-700">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                Why the agent chose{providerName ? ` ${providerName}` : " this supplier"}
              </p>
              {rankingEntry && (
                <span className="inline-flex items-center rounded-full border border-emerald-300 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                  Score {(rankingEntry.composite_score * 100).toFixed(0)}% · Rank #{rankingEntry.rank}
                </span>
              )}
            </div>

            {llmLoading && (
              <div className="space-y-1.5" role="status" aria-label="Generating explanation">
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3.5 w-3/5" />
              </div>
            )}

            {!llmLoading && llmText && (
              <p className="text-sm text-foreground leading-relaxed">{llmText}</p>
            )}

            {!llmLoading && llmError && (
              <p className="text-xs text-muted-foreground italic">
                Could not generate explanation — ensure the IntentParser is running
                (<span className="font-mono">uvicorn api:app --port 8001</span>).
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
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

// ── Session persistence helper ───────────────────────────────────────────────
// Persist a confirmed RunResult to the WizardSession store so the order page
// can render Payment, Contract, Reasoning, and Live Tracking without a DB
// round-trip. Used by both handleProceed (advisory/hitl) and the confirmed
// useEffect (autonomous). Always overwrites so stale sessions are replaced.
function persistConfirmedSession(result: RunResult): void {
  if (!result.request_id) return
  const offerings   = result.offerings ?? []
  const chosenItemId = result.decision?.final_item_id ?? result.recommended_item_id ?? null
  const chosenOffer  = offerings.find((o) => o.item_id === chosenItemId)
  if (!offerings.length || !chosenOffer) return

  const commit = {
    transaction_id:  result.transaction_id,
    request_id:      result.request_id,
    order_id:        result.order_id        ?? null,
    order_state:     result.order_state     ?? null,
    payment_terms:   result.payment_terms   ?? null,
    fulfillment_eta: null,
    bpp_id:          result.bpp_id          ?? "",
    bpp_uri:         result.bpp_uri         ?? "",
    contract_id:     result.contract_id     ?? null,
    reasoning_steps: result.reasoning_steps ?? [],
    messages:        result.messages        ?? [],
    status:          result.status          ?? "live",
  }
  const negotiation =
    result.negotiation_settled_price != null && result.negotiation_settled_price > 0
      ? { settled_price: result.negotiation_settled_price, agreed_delivery_date: null }
      : null

  saveSession(result.request_id, {
    intent:      { quantity: chosenOffer.available_quantity ?? 1 } as BecknIntent,
    comparison:  {
      transaction_id:      result.transaction_id,
      request_id:          result.request_id,
      offerings,
      recommended_item_id: chosenItemId,
      scoring:             result.scoring ?? { recommended_item_id: null, criteria: [], ranking: [] },
      reasoning_steps:     result.reasoning_steps ?? [],
      messages:            result.messages        ?? [],
      status:              "live",
    } as ComparisonResult,
    chosenItemId,
    commit,
    negotiation,
  })
}

// ── Main RunView ──────────────────────────────────────────────────────────────

export default function RunView({ runId }: RunViewProps) {
  const router = useRouter()

  const [run,        setRun]        = useState<RunResult | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState("")

  // Guard is active only while the user is in an interactive stage and has a
  // request that can still be cancelled. Terminal stages disable it.
  const TERMINAL_STAGES = new Set(["confirmed", "rejected", "no_offerings", "awaiting_rbac_approval"])
  const guardEnabled = !loading && run !== null && !TERMINAL_STAGES.has(run.stage)

  const { showModal: showLeaveModal, confirming: cancellingRequest,
          dismiss: dismissLeave, confirmLeave, trigger: triggerLeave } = useNavigationGuard(
    guardEnabled,
    async (target) => {
      if (run?.request_id) {
        try { await cancelRequest(run.request_id) } catch { /* handled by TTL cleanup */ }
      }
      router.push(target)
    },
  )

  // Redirect to the full order page whenever the run reaches the confirmed stage.
  // persistConfirmedSession writes the WizardSession for all modes (autonomous,
  // advisory, hitl) — overwriting any stale session from a prior attempt.
  useEffect(() => {
    if (run?.stage !== "confirmed" || !run.request_id) return
    persistConfirmedSession(run)
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
      // Advisory / HITL: save the WizardSession synchronously here so the order
      // page has Payment, Contract, and Reasoning before the useEffect fires.
      if (result.stage === "confirmed") persistConfirmedSession(result)
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
          <SelectionExplanationCard run={run} recommendedItemId={recommendedItemId} />
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
          onClick={() => guardEnabled ? triggerLeave("/request/new") : router.push("/request/new")}
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

      {/* ── Leave / cancel confirmation ────────────────────────────────────── */}
      <Dialog open={showLeaveModal} onOpenChange={(o) => { if (!o) dismissLeave() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel this request?</DialogTitle>
            <DialogDescription>
              If you leave now, this procurement request will be automatically
              cancelled. You will not be able to resume it later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex flex-col-reverse sm:flex-row gap-2">
            <Button variant="outline" onClick={dismissLeave} disabled={cancellingRequest}>
              Stay on page
            </Button>
            <Button variant="destructive" onClick={confirmLeave} disabled={cancellingRequest}>
              {cancellingRequest ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Cancelling…
                </>
              ) : (
                "Yes, cancel request"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
