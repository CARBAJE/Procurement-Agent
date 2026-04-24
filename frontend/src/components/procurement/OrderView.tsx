"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Hash, AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import OrderSummaryCard       from "@/components/procurement/OrderSummaryCard"
import OrderLifecycleTimeline from "@/components/procurement/OrderLifecycleTimeline"
import ReasoningPanel         from "@/components/procurement/ReasoningPanel"
import StatusPoller           from "@/components/procurement/StatusPoller"
import { loadSession, patchSession } from "@/lib/session-store"
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
}

export default function OrderView({ txnId }: OrderViewProps) {
  const router = useRouter()
  const [resolved, setResolved] = useState<ResolvedSession | null>(null)
  const [state,    setState]    = useState<OrderState | null>(null)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const session = loadSession(txnId)
    if (session?.commit && session.chosenItemId) {
      const offering = session.comparison.offerings.find(
        (o) => o.item_id === session.chosenItemId,
      )
      if (offering) {
        setResolved({
          commit: session.commit,
          offering,
          intent: session.intent,
        })
        setState(session.commit.order_state ?? null)
      }
    }
    setHydrated(true)
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
            We could not find a stored order for this request in the current session.
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
          <p className="text-xs text-muted-foreground mb-1">
            <span className="text-foreground">Request</span>
            {" → "}
            <span className="text-foreground">Compare offers</span>
            {" → "}
            <span className="text-foreground font-medium">Order</span>
          </p>
          <h1 className="text-3xl font-bold">Order</h1>
          <div className="flex items-center gap-1.5 mt-1">
            <Hash className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-mono">{commit.transaction_id}</span>
          </div>
        </div>
        <Badge variant={commit.status === "live" ? "default" : "secondary"} className="text-sm px-3 py-1">
          {commit.status === "live" ? "Live Beckn Network" : "Local Catalog"}
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <OrderSummaryCard commit={commit} offering={offering} quantity={intent.quantity} />
          <StatusPoller
            transactionId={commit.transaction_id}
            orderId={commit.order_id}
            bppId={commit.bpp_id}
            bppUri={commit.bpp_uri}
            initialState={state}
            onUpdate={onUpdate}
          />
          <ReasoningPanel
            steps={commit.reasoning_steps}
            messages={commit.messages}
            title="How we got here"
          />
        </div>
        <div className="space-y-6">
          <OrderLifecycleTimeline state={state} />
          <div className="flex flex-col gap-2">
            <Button variant="outline" onClick={() => router.push("/dashboard")}>
              Back to Dashboard
            </Button>
            <Button variant="ghost" onClick={() => router.push("/request/new")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              New request
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
