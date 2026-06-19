"use client"

import { Receipt, CreditCard, Hash, CheckCircle2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import type { CommitResult, Offering, PaymentTerms } from "@/lib/types"
import type { NegotiatedTerms } from "@/lib/session-store"

interface OrderSummaryCardProps {
  commit: CommitResult
  offering: Offering
  quantity?: number
  /** Terms settled in the negotiation step, if the user went through it. */
  negotiated?: NegotiatedTerms | null
}

function formatPayment(p: PaymentTerms | null): string {
  if (!p) return "—"
  const kind = p.type === "ON_FULFILLMENT" ? "Cash on delivery" :
               p.type === "ON_ORDER"        ? "Pre-payment"      :
               p.type === "POST_FULFILLMENT" ? "Invoice"          :
               p.type
  return `${kind} · collected by ${p.collected_by}`
}

export default function OrderSummaryCard({ commit, offering, quantity, negotiated }: OrderSummaryCardProps) {
  const listPrice = parseFloat(offering.price_value)
  const settled = negotiated?.settled_price ?? null
  const hasNegotiated = settled != null && Number.isFinite(settled)
  const unitPrice = hasNegotiated ? (settled as number) : listPrice
  const savings = hasNegotiated ? Math.max(0, listPrice - (settled as number)) : 0
  const cur = offering.price_currency
  const total = quantity != null ? (unitPrice * quantity).toFixed(2) : null

  return (
    <Card className="border-green-500/40 bg-gradient-to-br from-green-50/60 to-emerald-50/40 dark:from-green-950/30 dark:to-emerald-950/20">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
          Order confirmed
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="font-mono text-xs">
            <Hash className="h-3 w-3 mr-1" />
            {commit.order_id ?? "Pending"}
          </Badge>
        </div>

        <div>
          <p className="text-2xl font-bold">{offering.provider_name}</p>
          <p className="text-sm text-muted-foreground">{offering.item_name}</p>
        </div>

        <Separator />

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Unit price</p>
            {hasNegotiated ? (
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-semibold tabular-nums">{cur} {unitPrice.toFixed(2)}</span>
                <span className="text-xs text-muted-foreground line-through tabular-nums">
                  {cur} {listPrice.toFixed(2)}
                </span>
                <Badge variant="secondary" className="text-[10px]">Negotiated</Badge>
              </div>
            ) : (
              <p className="font-semibold tabular-nums">{cur} {offering.price_value}</p>
            )}
          </div>
          {total && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Total × {quantity}</p>
              <p className="font-bold tabular-nums">{cur} {total}</p>
            </div>
          )}
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
              <CreditCard className="h-3 w-3" />
              Payment
            </p>
            <p className="text-sm">{formatPayment(commit.payment_terms)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
              <Receipt className="h-3 w-3" />
              Contract
            </p>
            <p className="font-mono text-xs truncate">
              {commit.contract_id ? `${commit.contract_id.slice(0, 8)}…` : "—"}
            </p>
          </div>
        </div>

        {hasNegotiated && (
          <>
            <Separator />
            <p className="text-sm">
              <span className="text-muted-foreground">Negotiated savings:</span>{" "}
              <span className="font-semibold tabular-nums text-green-600 dark:text-green-400">
                {cur} {savings.toFixed(2)}/unit
              </span>
              {quantity != null && savings > 0 && (
                <> · {cur} {(savings * quantity).toFixed(2)} total</>
              )}
            </p>
            {negotiated?.agreed_delivery_date && (
              <p className="text-sm">
                <span className="text-muted-foreground">Agreed delivery:</span>{" "}
                <span className="font-medium tabular-nums">{negotiated.agreed_delivery_date}</span>
              </p>
            )}
          </>
        )}

        {commit.fulfillment_eta && (
          <>
            <Separator />
            <p className="text-sm">
              <span className="text-muted-foreground">ETA:</span>{" "}
              <span className="font-medium">{commit.fulfillment_eta}</span>
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
