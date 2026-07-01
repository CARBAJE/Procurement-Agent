"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import { ArrowLeft, Send, AlertCircle, Hash, Info, Loader2, Handshake, Eye, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import ComparisonTable      from "@/components/procurement/ComparisonTable"
import ScoringPanel         from "@/components/procurement/ScoringPanel"
import ReasoningPanel       from "@/components/procurement/ReasoningPanel"
import ConfirmCommitDialog  from "@/components/procurement/ConfirmCommitDialog"
import ConfirmCancelDialog  from "@/components/procurement/ConfirmCancelDialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { commitOrder, cancelRequest } from "@/lib/api"
import { clearSession, loadSession, patchSession } from "@/lib/session-store"
import type { CommitResult, ComparisonResult, BecknIntent } from "@/lib/types"

interface CompareViewProps {
  txnId: string
}

export default function CompareView({ txnId }: CompareViewProps) {
  const router = useRouter()
  const { data: session } = useSession()
  const role = session?.user.role ?? "requester"

  const [comparison, setComparison] = useState<ComparisonResult | null>(null)
  const [intent,     setIntent]     = useState<BecknIntent | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hydrated,   setHydrated]   = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState("")
  const [pendingApproval, setPendingApproval] = useState<CommitResult | null>(null)
  const [budgetDialogOpen, setBudgetDialogOpen] = useState(false)

  // Rehydrate from sessionStorage.
  useEffect(() => {
    const session = loadSession(txnId)
    if (session) {
      setComparison(session.comparison)
      setIntent(session.intent)
      setSelectedId(session.chosenItemId ?? session.comparison.recommended_item_id)
    }
    setHydrated(true)
  }, [txnId])

  // Persist the user's current pick as they browse.
  useEffect(() => {
    if (!hydrated || !comparison) return
    patchSession(txnId, { chosenItemId: selectedId })
  }, [selectedId, hydrated, comparison, txnId])

  async function cancel() {
    const requestId = comparison?.request_id
    if (!requestId) {
      setCancelDialogOpen(false)
      setError("Unable to cancel this request. Please try again or contact support.")
      return
    }
    setSubmitting(true)
    setError("")
    try {
      await cancelRequest(requestId)
    } catch (err) {
      console.error("[cancel] failed for requestId:", requestId, err)
      setCancelDialogOpen(false)
      setError("Unable to cancel the request. Please try again.")
      setSubmitting(false)
      return
    }
    clearSession(txnId)
    router.push("/request/new")
  }

  async function doCommit() {
    if (!comparison || !selectedId) return
    setSubmitting(true)
    setError("")
    try {
      const result = await commitOrder(txnId, selectedId)
      if (result.status === "pending_approval") {
        setDialogOpen(false)
        setPendingApproval(result)
        setSubmitting(false)
        return
      }
      patchSession(txnId, { commit: result })
      router.push(`/request/${encodeURIComponent(txnId)}/order`)
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setError("Your role does not allow placing orders.")
      } else {
        setError("Unable to place the order. Please try again.")
      }
      // eslint-disable-next-line no-console
      console.error("commit error", e)
      setSubmitting(false)
    }
  }

  function onProceed() {
    if (!comparison || !selectedId) return
    // Budget gate: if the order total exceeds the user's stated maximum,
    // pause here and ask for explicit confirmation. Does not affect
    // the "Negotiate Terms" path — negotiation is a price-reduction step.
    const offer = comparison.offerings.find((o) => o.item_id === selectedId)
    const budgetMax = intent?.budget_constraints?.max ?? null
    if (offer && budgetMax !== null) {
      const totalCost = parseFloat(offer.price_value) * (intent?.quantity ?? 1)
      if (totalCost > budgetMax) {
        setBudgetDialogOpen(true)
        return
      }
    }
    // Happy path (recommended) → no dialog, straight to commit.
    // Alternative pick → confirm dialog with diff.
    if (selectedId === comparison.recommended_item_id) {
      doCommit()
    } else {
      setDialogOpen(true)
    }
  }

  function onProceedDespiteBudget() {
    setBudgetDialogOpen(false)
    if (!comparison || !selectedId) return
    if (selectedId === comparison.recommended_item_id) {
      doCommit()
    } else {
      setDialogOpen(true)
    }
  }

  // Step into the negotiation flow with the selected supplier's quoted terms.
  function goNegotiate() {
    const offer = comparison?.offerings.find((o) => o.item_id === selectedId)
    if (!offer) return
    const listPrice = parseFloat(offer.price_value)
    const hours = offer.fulfillment_hours ?? intent?.delivery_timeline ?? 336
    const deliveryDate = new Date(Date.now() + hours * 3_600_000)
      .toISOString()
      .slice(0, 10)
    const qty = intent?.quantity ?? offer.available_quantity ?? 1
    const params = new URLSearchParams({
      supplier_id: offer.provider_id,
      item_id: offer.item_id,
      original_price: String(Number.isFinite(listPrice) ? listPrice : 0),
      delivery_date: deliveryDate,
      item: offer.item_name,
      quantity: String(qty),
    })
    router.push(
      `/request/${encodeURIComponent(txnId)}/negotiate?${params.toString()}`,
    )
  }

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (!hydrated) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2"><Skeleton className="h-64 w-full" /></div>
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    )
  }

  // ── Missing comparison (direct URL, expired session) ─────────────────────
  if (!comparison) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-destructive" />
            Comparison unavailable
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            We could not find a stored comparison for this request. It may have
            expired or been opened in a different browser tab.
          </p>
          <Button onClick={() => router.push("/request/new")}>
            Start a new request
          </Button>
        </CardContent>
      </Card>
    )
  }

  const { offerings, scoring, reasoning_steps, messages, recommended_item_id } = comparison
  const recommended = offerings.find((o) => o.item_id === recommended_item_id)
  const selected    = offerings.find((o) => o.item_id === selectedId)

  // Pending approval success state — replace action bar with confirmation banner.
  if (pendingApproval) {
    return (
      <div className="space-y-6">
        <Card className="border-amber-500/40 bg-amber-50/60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-amber-800">
              <Clock className="h-5 w-5 shrink-0" aria-hidden="true" />
              Order Submitted for Approval
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-amber-900">
            <p>
              Your order total of{" "}
              <strong>
                ₹{(pendingApproval.amount_total ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </strong>{" "}
              exceeds your auto-approval threshold and has been routed to an approver.
            </p>
            <p className="text-xs text-amber-700">
              Reference ID: <span className="font-mono">{pendingApproval.request_id}</span>
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push("/request/new")}
            >
              Start a new request
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const budgetMax = intent?.budget_constraints?.max ?? null
  const orderTotal = selected ? parseFloat(selected.price_value) * (intent?.quantity ?? 1) : 0
  const budgetOverage = budgetMax !== null && orderTotal > budgetMax ? orderTotal - budgetMax : null

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <p className="text-xs text-muted-foreground mb-1">
            <span className="text-foreground">Request</span>
            {" → "}
            <span className="text-foreground font-medium">Compare offers</span>
            {" → "}
            Confirm order
          </p>
          <h1 className="text-4xl font-extrabold tracking-tight">Compare Offers</h1>
          <div className="flex items-center gap-1.5 mt-1">
            <Hash className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-mono">
              {comparison.transaction_id}
            </span>
          </div>
        </div>
        {role === "admin" && (
          <Badge variant="outline" className="flex items-center gap-1 text-xs">
            <Eye className="h-3 w-3" aria-hidden="true" />
            View Only
          </Badge>
        )}
      </div>

      {/* ── Table + scoring panel ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* min-w-0: lets this grid column shrink to its track width instead of
            growing to the table's intrinsic width (default min-width:auto),
            which is what caused the table to overflow / scroll horizontally. */}
        <div className="lg:col-span-2 space-y-3 min-w-0">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="h-4 w-0.5 rounded-full bg-primary shrink-0" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">{offerings.length} Offerings</h2>
              <span className="text-xs text-muted-foreground">— sort by any column</span>
            </div>
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
              <Info className="h-3 w-3" />
              Arrow keys to navigate, Enter to select
            </span>
          </div>
          <ComparisonTable
            offerings={offerings}
            recommendedItemId={recommended_item_id}
            selectedItemId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
        <div>
          <ScoringPanel
            scoring={scoring}
            offerings={offerings}
            selectedItemId={selectedId}
          />
        </div>
      </div>

      {/* ── Action bar ────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between pt-2 border-t flex-wrap gap-3">
        <Button
          variant="outline"
          onClick={() => setCancelDialogOpen(true)}
          disabled={submitting}
        >
          <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
          Cancel and start over
        </Button>
        {role === "admin" ? (
          <p role="status" className="text-sm text-muted-foreground">
            Advisory mode — orders cannot be placed with the admin role.
          </p>
        ) : (
          <div className="flex items-center gap-3 flex-wrap">
            {selectedId && selectedId !== recommended_item_id && (
              <span className="text-xs text-muted-foreground">
                Non-recommended choice — you will be asked to confirm
              </span>
            )}
            <Button
              variant="outline"
              disabled={!selectedId || submitting}
              onClick={goNegotiate}
            >
              <Handshake className="mr-2 h-4 w-4" aria-hidden="true" />
              Negotiate Terms
            </Button>
            <Button
              disabled={!selectedId || submitting}
              onClick={onProceed}
              aria-busy={submitting}
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Placing order…
                </>
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" aria-hidden="true" />
                  Proceed with selection
                </>
              )}
            </Button>
          </div>
        )}
      </div>

      {submitting && !error && (
        <p role="status" className="text-xs text-muted-foreground text-right">
          Placing your order through the Beckn network — this can take a few seconds.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive text-right">{error}</p>
      )}

      {/* ── Reasoning trace ───────────────────────────────────────────────── */}
      <ReasoningPanel steps={reasoning_steps} messages={messages} />

      {/* ── Confirm dialog (only for non-recommended picks) ──────────────── */}
      {recommended && selected && (
        <ConfirmCommitDialog
          open={dialogOpen}
          onOpenChange={(o) => { if (!submitting) setDialogOpen(o) }}
          recommended={recommended}
          selected={selected}
          quantity={intent?.quantity}
          submitting={submitting}
          onConfirm={doCommit}
        />
      )}

      {/* ── Cancel confirmation dialog ───────────────────────────────────── */}
      <ConfirmCancelDialog
        open={cancelDialogOpen}
        onOpenChange={(o) => { if (!submitting) setCancelDialogOpen(o) }}
        submitting={submitting}
        onConfirm={cancel}
      />

      {/* ── Budget exceeded confirmation dialog ──────────────────────────── */}
      <Dialog
        open={budgetDialogOpen}
        onOpenChange={(o) => { if (!submitting) setBudgetDialogOpen(o) }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-destructive" aria-hidden="true" />
              Order exceeds your budget
            </DialogTitle>
            <DialogDescription>
              This order total of{" "}
              <strong>₹{orderTotal.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>{" "}
              exceeds your stated maximum of{" "}
              <strong>₹{(budgetMax ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>{" "}
              by{" "}
              <strong>₹{(budgetOverage ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>.
              You can proceed or go back to choose a different offering.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setBudgetDialogOpen(false)}
              disabled={submitting}
            >
              Choose a different offering
            </Button>
            <Button onClick={onProceedDespiteBudget} disabled={submitting}>
              Continue anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
