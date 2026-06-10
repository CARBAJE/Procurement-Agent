"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Send, AlertCircle, Hash, Info, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import ComparisonTable      from "@/components/procurement/ComparisonTable"
import ScoringPanel         from "@/components/procurement/ScoringPanel"
import ReasoningPanel       from "@/components/procurement/ReasoningPanel"
import ConfirmCommitDialog  from "@/components/procurement/ConfirmCommitDialog"
import ConfirmCancelDialog  from "@/components/procurement/ConfirmCancelDialog"
import { commitOrder, cancelRequest } from "@/lib/api"
import { clearSession, loadSession, patchSession } from "@/lib/session-store"
import type { ComparisonResult, BecknIntent } from "@/lib/types"

interface CompareViewProps {
  txnId: string
}

export default function CompareView({ txnId }: CompareViewProps) {
  const router = useRouter()
  const [comparison, setComparison] = useState<ComparisonResult | null>(null)
  const [intent,     setIntent]     = useState<BecknIntent | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hydrated,   setHydrated]   = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState("")

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
      setError(
        "No request_id available for this comparison — the DB row was never created. " +
        "Check that the data-normalizer container is running.",
      )
      return
    }
    setSubmitting(true)
    setError("")
    try {
      await cancelRequest(requestId)
    } catch (err) {
      console.error("[cancel] failed for requestId:", requestId, err)
      setCancelDialogOpen(false)
      setError(
        "Could not mark the request as cancelled in the database. " +
        "The data-normalizer may be offline — check the logs.",
      )
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
      patchSession(txnId, { commit: result })
      router.push(`/request/${encodeURIComponent(txnId)}/order`)
    } catch (e) {
      setError("Could not commit the order. The BAP backend may be offline.")
      // eslint-disable-next-line no-console
      console.error("commit error", e)
      setSubmitting(false)
    }
  }

  function onProceed() {
    // Happy path (recommended) → no dialog, straight to commit.
    // Alternative pick → confirm dialog with diff.
    if (!comparison || !selectedId) return
    if (selectedId === comparison.recommended_item_id) {
      doCommit()
    } else {
      setDialogOpen(true)
    }
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
        <div className="flex items-center gap-3 flex-wrap">
          {selectedId && selectedId !== recommended_item_id && (
            <span className="text-xs text-muted-foreground">
              Non-recommended choice — you will be asked to confirm
            </span>
          )}
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
    </div>
  )
}
