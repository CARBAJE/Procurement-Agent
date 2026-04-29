"use client"

import { Receipt, CreditCard, Hash, CheckCircle2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import type { CommitResult, Offering, PaymentTerms } from "@/lib/types"

interface OrderSummaryCardProps {
  commit: CommitResult
  offering: Offering
  quantity?: number
}

function formatPayment(p: PaymentTerms | null): string {
  if (!p) return "—"
  const kind = p.type === "ON_FULFILLMENT" ? "Cash on delivery" :
               p.type === "ON_ORDER"        ? "Pre-payment"      :
               p.type === "POST_FULFILLMENT" ? "Invoice"          :
               p.type
  return `${kind} · collected by ${p.collected_by}`
}

export default function OrderSummaryCard({ commit, offering, quantity }: OrderSummaryCardProps) {
  const total = quantity != null
    ? (parseFloat(offering.price_value) * quantity).toFixed(2)
    : null

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
            {commit.order_id}
          </Badge>
          {commit.status === "mock" && (
            <Badge variant="secondary" className="text-xs">Local Catalog</Badge>
          )}
        </div>

        <div>
          <p className="text-2xl font-bold">{offering.provider_name}</p>
          <p className="text-sm text-muted-foreground">{offering.item_name}</p>
        </div>

        <Separator />

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Unit price</p>
            <p className="font-semibold tabular-nums">{offering.price_currency} {offering.price_value}</p>
          </div>
          {total && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Total × {quantity}</p>
              <p className="font-bold tabular-nums">{offering.price_currency} {total}</p>
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
