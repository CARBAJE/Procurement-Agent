"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { AlertCircle, Hash, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import NegotiationStepper from "@/components/procurement/NegotiationStepper"
import { commitOrder } from "@/lib/api"
import { patchSession } from "@/lib/session-store"

export interface NegotiateViewProps {
  txnId: string
  supplierId?: string
  supplierName?: string
  itemId?: string
  item?: string
  quantity?: number
  listPrice?: number
  deliveryDate?: string
}

/**
 * Negotiation step in the procurement flow: compare → **negotiate** → order.
 *
 * Pre-fills the negotiation with the supplier terms selected on the compare
 * page and reuses the shared <NegotiationStepper/>. On acceptance it commits
 * the order (same path as the compare page) and forwards the settled terms.
 */
export default function NegotiateView({
  txnId,
  supplierId,
  supplierName,
  itemId,
  item,
  quantity,
  listPrice,
  deliveryDate,
}: NegotiateViewProps) {
  const router = useRouter()
  const [committing, setCommitting] = useState(false)
  const [error, setError] = useState("")

  const hasTerms = Boolean(supplierId && item && listPrice && listPrice > 0)
  // Buyer aims for ~18% below the supplier's list price — inside the engine's
  // hard 20% discount guardrail, leaving real room to converge.
  const targetPrice = hasTerms ? Math.max(1, Math.round((listPrice as number) * 0.82)) : 0

  async function proceedToOrder(settled: {
    price: number | null
    deliveryDate: string | null
  }) {
    patchSession(txnId, {
      chosenItemId: itemId ?? null,
      negotiation: {
        settled_price: settled.price,
        agreed_delivery_date: settled.deliveryDate,
        supplier_id: supplierId ?? null,
      },
    })
    if (!itemId) {
      router.push(`/request/${encodeURIComponent(txnId)}/order`)
      return
    }
    setCommitting(true)
    setError("")
    try {
      const result = await commitOrder(txnId, itemId)
      patchSession(txnId, { commit: result })
      router.push(`/request/${encodeURIComponent(txnId)}/order`)
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("commit error", e)
      setError("Could not commit the order. The BAP backend may be offline.")
      setCommitting(false)
    }
  }

  function backToCompare() {
    router.push(`/request/${encodeURIComponent(txnId)}/compare`)
  }

  return (
    <div className="space-y-6">
      {/* Header + breadcrumb */}
      <div>
        <p className="text-xs text-muted-foreground mb-1">
          <span className="text-foreground">Request</span>
          {" → "}
          <span className="text-foreground">Compare offers</span>
          {" → "}
          <span className="text-foreground font-medium">Negotiate</span>
          {" → "}
          Confirm order
        </p>
        <h1 className="text-4xl font-extrabold tracking-tight">Negotiate Terms</h1>
        <div className="flex items-center gap-1.5 mt-1">
          <Hash className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs text-muted-foreground font-mono">{txnId}</span>
        </div>
      </div>

      {!hasTerms ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-destructive" aria-hidden="true" />
              Negotiation context missing
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Open this step from the compare page so the selected supplier&apos;s
              quoted price and delivery date can be carried into the negotiation.
            </p>
            <Button onClick={backToCompare}>Back to Compare</Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <NegotiationStepper
            initialItem={item}
            initialQuantity={quantity ?? 1}
            initialTargetPrice={targetPrice}
            initialListPrice={listPrice}
            initialRequestedDeliveryDate={deliveryDate}
            supplierId={supplierId}
            supplierName={supplierName}
            autoStart
            hideForm
            onProceed={proceedToOrder}
            onReject={backToCompare}
          />

          {committing && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              Placing your order through the Beckn network…
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </>
      )}
    </div>
  )
}
