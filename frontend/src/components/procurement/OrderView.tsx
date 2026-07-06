"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Hash, AlertCircle, ShieldCheck, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import OrderSummaryCard       from "@/components/procurement/OrderSummaryCard"
import OrderLifecycleTimeline from "@/components/procurement/OrderLifecycleTimeline"
import ReasoningPanel         from "@/components/procurement/ReasoningPanel"
import StatusPoller           from "@/components/procurement/StatusPoller"
import { loadSession, patchSession, type NegotiatedTerms } from "@/lib/session-store"
import { getOrderDetail } from "@/lib/api"
import type {
  BecknIntent, CommitResult, Offering, OrderState, StatusSnapshot,
} from "@/lib/types"

interface OrderViewProps {
  txnId: string
}

interface ResolvedSession {
  commit: CommitResult
  offering: Offering
  intent: BecknIntent
  negotiated: NegotiatedTerms | null
}

export default function OrderView({ txnId }: OrderViewProps) {
  const router = useRouter()
  const [resolved,   setResolved]   = useState<ResolvedSession | null>(null)
  const [state,      setState]      = useState<OrderState | null>(null)
  const [hydrated,   setHydrated]   = useState(false)
  // Historical = reconstructed from the DB (no live session) → no live polling.
  const [historical, setHistorical] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function load() {
      // 1. Live session (the tab that created the order) — full fidelity.
      const session = loadSession(txnId)
      if (session?.commit && session.chosenItemId) {
        const offering = session.comparison.offerings.find(
          (o) => o.item_id === session.chosenItemId,
        )
        if (offering) {
          if (!cancelled) {
            setResolved({
              commit: session.commit,
              offering,
              intent: session.intent,
              negotiated: session.negotiation ?? null,
            })
            setState(session.commit.order_state ?? null)
            setHydrated(true)
          }
          return
        }
      }

      // 2. No session (e.g. opened from the dashboard) — fetch from the DB by
      //    request_id (the URL param in the dashboard flow).
      try {
        const d = await getOrderDetail(txnId)
        if (cancelled) return
        if (d.order && d.intent) {
          const o = d.order
          const commit: CommitResult = {
            transaction_id:  d.request_id,
            request_id:      d.request_id,
            order_id:        o.order_id,
            order_state:     o.order_state,
            payment_terms:   o.payment_terms   ?? null,
            fulfillment_eta: o.fulfillment_eta,
            bpp_id:          o.bpp_id,
            bpp_uri:         o.bpp_uri,
            contract_id:     o.contract_id     ?? null,
            reasoning_steps: o.reasoning_steps ?? [],
            messages:        o.messages        ?? [],
            status:          o.status,
          }
          setResolved({ commit, offering: o.offering, intent: d.intent, negotiated: null })
          setState(o.order_state)
          setHistorical(true)
        }
      } catch {
        // Unknown request_id / backend down → fall through to "unavailable".
      } finally {
        if (!cancelled) setHydrated(true)
      }
    }

    load()
    return () => { cancelled = true }
  }, [txnId])

  const onUpdate = useCallback((snap: StatusSnapshot) => {
    setState(snap.state)
    if (resolved) {
      const nextCommit = { ...resolved.commit, order_state: snap.state }
      setResolved({ ...resolved, commit: nextCommit })
      patchSession(txnId, { commit: nextCommit })
    }
  }, [resolved, txnId])

  // ── Loading skeleton ─────────────────────────────────────────────────────
  if (!hydrated) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="h-80 w-full lg:col-span-2" />
          <Skeleton className="h-80 w-full" />
        </div>
      </div>
    )
  }

  // ── Missing session (refresh in another tab, etc.) ──────────────────────
  if (!resolved) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-destructive" />
            Order unavailable
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            We could not find a confirmed order for this request. It may still be
            in progress, may have been cancelled, or the request id is unknown.
          </p>
          <Button onClick={() => router.push("/request/new")}>Start a new request</Button>
        </CardContent>
      </Card>
    )
  }

  const { commit, offering, intent } = resolved

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <Button variant="ghost" size="sm" asChild className="-ml-2 mb-1">
            <Link href="/dashboard">
              <ArrowLeft className="h-4 w-4 mr-1" aria-hidden="true" />
              Back to Dashboard
            </Link>
          </Button>
          <h1 className="text-4xl font-extrabold tracking-tight">Order Confirmed</h1>
          <div className="flex items-center gap-1.5 mt-1">
            <Hash className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-mono">{commit.transaction_id}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <OrderSummaryCard commit={commit} offering={offering} quantity={intent.quantity} negotiated={resolved.negotiated} />
          {!historical && commit.order_id != null && (
            <StatusPoller
              transactionId={commit.transaction_id}
              orderId={commit.order_id}
              bppId={commit.bpp_id}
              bppUri={commit.bpp_uri}
              initialState={state}
              onUpdate={onUpdate}
            />
          )}
          <ReasoningPanel
            steps={commit.reasoning_steps}
            messages={commit.messages}
            title="How we got here"
          />
        </div>
        <div className="space-y-6">
          <OrderLifecycleTimeline state={state} />
          <div className="flex flex-col gap-2">
            <Button
              className="bg-blue-600 hover:bg-blue-700 text-white border-0"
              onClick={() => router.push("/request/new")}
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
              New request
            </Button>
            <Button className="bg-green-600 hover:bg-green-700 text-white border-0" asChild>
              <Link href={`/request/${txnId}/audit`}>
                <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
                View Audit Trail
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
