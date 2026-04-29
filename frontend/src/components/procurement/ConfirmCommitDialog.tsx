"use client"

import { Loader2, Send, ArrowRight, Info } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import type { Offering } from "@/lib/types"

interface ConfirmCommitDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  recommended: Offering
  selected: Offering
  quantity?: number
  submitting: boolean
  onConfirm: () => void
  /** Future hook for Approval Workflow (see plan §extension points). */
  requiresApproval?: boolean
}

function diffLine(label: string, current: string | number, baseline: string | number): string | null {
  if (current === baseline) return null
  return `${label}: ${baseline} → ${current}`
}

export default function ConfirmCommitDialog({
  open,
  onOpenChange,
  recommended,
  selected,
  quantity,
  submitting,
  onConfirm,
  requiresApproval = false,
}: ConfirmCommitDialogProps) {
  const isSameAsRecommended = recommended.item_id === selected.item_id

  const priceDiff = parseFloat(selected.price_value) - parseFloat(recommended.price_value)
  const etaDiff   = (selected.fulfillment_hours ?? 0) - (recommended.fulfillment_hours ?? 0)

  const diffs: string[] = []
  if (!isSameAsRecommended) {
    if (priceDiff !== 0) {
      const sign = priceDiff > 0 ? "+" : ""
      diffs.push(`Price: ${sign}${selected.price_currency} ${priceDiff.toFixed(2)} per unit`)
    }
    if (selected.fulfillment_hours != null && recommended.fulfillment_hours != null && etaDiff !== 0) {
      const sign = etaDiff > 0 ? "+" : ""
      diffs.push(`ETA: ${sign}${etaDiff}h`)
    }
    const ratingLine = diffLine(
      "Rating",
      selected.rating ?? "—",
      recommended.rating ?? "—",
    )
    if (ratingLine) diffs.push(ratingLine)
  }

  const totalPrice = quantity != null
    ? `${selected.price_currency} ${(parseFloat(selected.price_value) * quantity).toFixed(2)}`
    : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isSameAsRecommended
              ? "Confirm order"
              : "Confirm alternative selection"}
          </DialogTitle>
          <DialogDescription>
            {isSameAsRecommended
              ? "You are confirming the agent's recommendation."
              : "You are about to order a different option than the agent recommended."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border bg-card p-4 space-y-2">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Your selection</p>
            <p className="font-semibold text-lg leading-tight">{selected.provider_name}</p>
            <p className="text-sm text-muted-foreground">{selected.item_name}</p>
            <Separator />
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Unit price</p>
                <p className="font-bold">{selected.price_currency} {selected.price_value}</p>
              </div>
              {totalPrice && (
                <div>
                  <p className="text-xs text-muted-foreground">Total × {quantity}</p>
                  <p className="font-bold">{totalPrice}</p>
                </div>
              )}
            </div>
          </div>

          {!isSameAsRecommended && diffs.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-50/60 dark:bg-amber-950/20 p-3 space-y-1.5">
              <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wide">
                vs. recommended ({recommended.provider_name})
              </p>
              <ul className="space-y-1 text-sm">
                {diffs.map((d, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <ArrowRight className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                    <span>{d}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {requiresApproval && (
            <div className="flex items-start gap-2 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
              <Info className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <p className="text-muted-foreground">
                This order exceeds your auto-approval threshold. It will be routed to an approver.
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Back
          </Button>
          <Button onClick={onConfirm} disabled={submitting}>
            {submitting ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Committing…</>
            ) : requiresApproval ? (
              <><Send className="mr-2 h-4 w-4" />Submit for approval</>
            ) : (
              <><Send className="mr-2 h-4 w-4" />Confirm order</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
