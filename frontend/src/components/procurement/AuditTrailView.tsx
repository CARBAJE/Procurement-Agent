"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { ArrowLeft, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import AuditTrailPanel from "@/components/procurement/AuditTrailPanel"
import { getAuditEvents } from "@/lib/api"
import type { AuditEvent } from "@/lib/types"

interface AuditTrailViewProps {
  requestId: string
}

export default function AuditTrailView({ requestId }: AuditTrailViewProps) {
  const [events, setEvents]   = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    getAuditEvents(requestId)
      .then((res) => setEvents(res.events))
      .catch(() => setError("Could not load audit trail. Check that the data-normalizer service is running."))
      .finally(() => setLoading(false))
  }, [requestId])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/request/${requestId}/order`} aria-label="Back to order">
            <ArrowLeft className="h-4 w-4 mr-1" aria-hidden="true" />
            Back
          </Link>
        </Button>
        <div className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-full bg-primary shrink-0" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Decision Audit Trail
          </h2>
        </div>
      </div>

      <p className="text-xs text-muted-foreground font-mono truncate">
        Request ID: {requestId}
      </p>

      {loading && (
        <div role="status" aria-live="polite" className="py-12 text-center text-sm text-muted-foreground">
          Loading audit events…
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {!loading && !error && (
        <AuditTrailPanel events={events} />
      )}
    </div>
  )
}
