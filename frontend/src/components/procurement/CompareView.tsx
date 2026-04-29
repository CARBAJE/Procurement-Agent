"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Send, AlertCircle, Hash, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import ComparisonTable      from "@/components/procurement/ComparisonTable"
import ScoringPanel         from "@/components/procurement/ScoringPanel"
import ReasoningPanel       from "@/components/procurement/ReasoningPanel"
import ConfirmCommitDialog  from "@/components/procurement/ConfirmCommitDialog"
import { commitOrder } from "@/lib/api"
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

  function cancel() {
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

  const { offerings, scoring, reasoning_steps, messages, status, recommended_item_id } = comparison
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
          <h1 className="text-3xl font-bold">Compare Offers</h1>
          <div className="flex items-center gap-1.5 mt-1">
            <Hash className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-mono">{comparison.transaction_id}</span>
          </div>
        </div>
        <Badge variant={status === "live" ? "default" : "secondary"} className="text-sm px-3 py-1">
          {status === "live" ? "Live Beckn Network" : "Local Catalog"}
        </Badge>
      </div>

      {/* ── Table + scoring panel ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {offerings.length} Offerings · Sort any column
            </h2>
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
        <Button variant="outline" onClick={cancel} disabled={submitting}>
          <ArrowLeft className="mr-2 h-4 w-4" />
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
            aria-label="Proceed with selection"
          >
            <Send className="mr-2 h-4 w-4" />
            Proceed with selection
          </Button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-destructive text-right">{error}</p>
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
    </div>
  )
}
