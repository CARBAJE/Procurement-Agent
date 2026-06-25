"use client"

import { useEffect, useRef, useState } from "react"
import { ArrowLeft, Bot, CheckCircle2, Loader2, ScanText, Store } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { useNegotiation, type NegotiationStatus } from "@/hooks/useNegotiation"
import { cn } from "@/lib/utils"

const STATUS_COPY: Record<NegotiationStatus, string> = {
  idle: "Ready to negotiate.",
  starting: "Starting negotiation — buyer agent is drafting its opening offer…",
  buyer_thinking: "Buyer agent is computing its next counter-offer…",
  supplier_thinking: "Supplier agent (qwen3:8b) is evaluating the offer…",
  done: "Negotiation complete.",
  error: "Negotiation failed.",
}

function inr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
}

function fmtDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "—"
}

export interface NegotiationStepperProps {
  /** Pre-fill the deal parameters (used when launched from the compare flow). */
  initialItem?: string
  initialQuantity?: number
  initialTargetPrice?: number
  initialListPrice?: number
  initialRequestedDeliveryDate?: string
  supplierId?: string
  supplierName?: string
  category?: string
  /** Start the negotiation automatically on mount (flow mode). */
  autoStart?: boolean
  /** Hide the editable deal-parameters form (flow mode). */
  hideForm?: boolean
  /** Shown as "Proceed to Order" once a deal is agreed. */
  onProceed?: (settled: { price: number | null; deliveryDate: string | null }) => void
  /** Shown as "Back to Compare" if the negotiation is rejected/escalated. */
  onReject?: () => void
}

/**
 * Live, autonomous two-agent negotiation visualiser.
 *
 * Buyer = the production LangGraph Negotiation Engine (deterministic strategy,
 * hard 20% discount guardrail). Supplier = a local qwen3:8b LLM. Each round is
 * a real round-trip on BOTH price and delivery date: the buyer parks on a full
 * counter-offer, the supplier model responds, and the buyer resumes.
 *
 * With no props it renders the standalone demo (editable form). With initial
 * props + `autoStart`/`hideForm` it is reused as a step in the request flow.
 */
export function NegotiationStepper({
  initialItem = "office chairs",
  initialQuantity = 50,
  initialTargetPrice = 150,
  initialListPrice = 180,
  initialRequestedDeliveryDate,
  supplierId,
  supplierName,
  category = "office_supplies",
  autoStart = false,
  hideForm = false,
  onProceed,
  onReject,
}: NegotiationStepperProps = {}) {
  const {
    status,
    snapshot,
    error,
    agreedPrice,
    agreedDeliveryDate,
    supplierModel,
    start,
    reset,
  } = useNegotiation()

  const [item, setItem] = useState(initialItem)
  const [quantity, setQuantity] = useState(initialQuantity)
  const [targetPrice, setTargetPrice] = useState(initialTargetPrice)
  const [listPrice, setListPrice] = useState(initialListPrice)
  const [maxRounds, setMaxRounds] = useState(3)

  const running =
    status === "starting" ||
    status === "buyer_thinking" ||
    status === "supplier_thinking"

  const history = snapshot?.history ?? []
  const requestedDelivery =
    snapshot?.requested_delivery_date ?? initialRequestedDeliveryDate ?? null
  // The gateway's authoritative "deal closed" signal is agreedPrice (set when
  // supplier-respond returns done). The engine's final_outcome can lag behind
  // the async Redis resume, so we don't gate the UI on it.
  const accepted =
    status === "done" &&
    (agreedPrice !== null || snapshot?.final_outcome === "accepted")
  const rejected =
    status === "done" && !accepted && snapshot?.final_outcome != null

  function handleStart() {
    void start({
      supplier_id: supplierId,
      supplier_name: supplierName,
      item,
      quantity,
      target_price: targetPrice,
      list_price: listPrice,
      requested_delivery_date: initialRequestedDeliveryDate,
      max_rounds: maxRounds,
      category,
    })
  }

  // Flow mode: kick off automatically once.
  const startedRef = useRef(false)
  useEffect(() => {
    if (autoStart && !startedRef.current) {
      startedRef.current = true
      handleStart()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart])

  return (
    <section aria-labelledby="negotiation-heading" className="space-y-4">
      <div className="flex items-center gap-2">
        <span
          className="h-5 w-1 rounded-full bg-primary shrink-0"
          aria-hidden="true"
        />
        <h2
          id="negotiation-heading"
          className="text-sm font-semibold text-foreground"
        >
          Live Agent Negotiation
        </h2>
      </div>

      {/* Agent identity cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <span
                className="rounded-md bg-primary/10 p-2 text-primary"
                aria-hidden="true"
              >
                <Bot className="h-4 w-4" />
              </span>
              <div>
                <CardTitle className="text-base">Buyer Agent</CardTitle>
                <CardDescription>LangGraph engine · 20% discount cap</CardDescription>
              </div>
            </div>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <span
                className="rounded-md bg-primary/10 p-2 text-primary"
                aria-hidden="true"
              >
                <Store className="h-4 w-4" />
              </span>
              <div>
                <CardTitle className="text-base">Supplier Agent</CardTitle>
                <CardDescription>
                  {supplierModel ? `${supplierModel} (local)` : "qwen3:8b (local)"}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
        </Card>
      </div>

      {/* Deal parameters + controls (hidden in flow mode) */}
      {!hideForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Deal parameters</CardTitle>
            <CardDescription>
              Set the buyer&apos;s target and the supplier&apos;s list price, then
              run the negotiation.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              <div className="col-span-2 sm:col-span-1 space-y-1.5">
                <Label htmlFor="neg-item">Item</Label>
                <Input
                  id="neg-item"
                  value={item}
                  onChange={(e) => setItem(e.target.value)}
                  disabled={running}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="neg-qty">Quantity</Label>
                <Input
                  id="neg-qty"
                  type="number"
                  min={1}
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                  disabled={running}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="neg-target">Target ₹/unit</Label>
                <Input
                  id="neg-target"
                  type="number"
                  min={1}
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(Number(e.target.value))}
                  disabled={running}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="neg-list">List ₹/unit</Label>
                <Input
                  id="neg-list"
                  type="number"
                  min={1}
                  value={listPrice}
                  onChange={(e) => setListPrice(Number(e.target.value))}
                  disabled={running}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="neg-rounds">Max rounds</Label>
                <Input
                  id="neg-rounds"
                  type="number"
                  min={1}
                  max={5}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                  disabled={running}
                />
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button onClick={handleStart} disabled={running}>
                {running ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    Negotiating…
                  </>
                ) : (
                  "Start negotiation"
                )}
              </Button>
              {(status === "done" || status === "error") && (
                <Button variant="outline" onClick={reset}>
                  Reset
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Live status — announced to assistive tech. */}
      <p
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 text-sm text-muted-foreground"
      >
        {running && (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        )}
        {status === "done" && (
          <CheckCircle2 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        )}
        {STATUS_COPY[status]}
        {requestedDelivery && (
          <span className="text-muted-foreground">
            · requested delivery by {fmtDate(requestedDelivery)}
          </span>
        )}
      </p>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {/* Round-by-round transcript */}
      {(history.length > 0 || running) && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Negotiation transcript</CardTitle>
            <CardDescription>
              {snapshot
                ? `Round ${snapshot.rounds_elapsed} of ${snapshot.max_rounds}`
                : "Starting…"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {history.length === 0 && (
              <p role="status" className="text-sm text-muted-foreground">
                Waiting for the first round…
              </p>
            )}
            <ol className="space-y-4">
              {history.map((turn) => (
                <li
                  key={turn.round_no}
                  className="rounded-md border border-border p-4"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Round {turn.round_no}
                    </span>
                    <SupplierActionBadge
                      action={turn.supplier_action}
                      source={turn.source}
                    />
                  </div>
                  <Separator className="my-3" />

                  {/* Buyer side — full message */}
                  <div className="flex items-start gap-2">
                    <Bot
                      className="mt-0.5 h-4 w-4 text-primary shrink-0"
                      aria-hidden="true"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">Buyer Engine</p>
                      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                        <dt className="text-muted-foreground">Price offer:</dt>
                        <dd className="tabular-nums font-medium">
                          {inr(turn.buyer_price_offer)}
                        </dd>
                        <dt className="text-muted-foreground">Delivery by:</dt>
                        <dd className="tabular-nums">{fmtDate(turn.buyer_delivery_offer)}</dd>
                        <dt className="text-muted-foreground">Quantity:</dt>
                        <dd className="tabular-nums">{turn.buyer_quantity} units</dd>
                      </dl>
                      {turn.buyer_justification && (
                        <p className="mt-1 flex items-start gap-1.5 text-sm text-muted-foreground">
                          <ScanText
                            className="mt-0.5 h-3.5 w-3.5 shrink-0"
                            aria-hidden="true"
                          />
                          <span className="italic">{turn.buyer_justification}</span>
                        </p>
                      )}
                    </div>
                  </div>

                  <Separator className="my-3" />

                  {/* Supplier side — full response */}
                  <div className="flex items-start gap-2">
                    <Store
                      className="mt-0.5 h-4 w-4 text-primary shrink-0"
                      aria-hidden="true"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">
                        Supplier ({supplierModel ?? "qwen3:8b"})
                      </p>
                      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                        <dt className="text-muted-foreground">Decision:</dt>
                        <dd className="font-medium uppercase">{turn.supplier_action}</dd>
                        {turn.supplier_action !== "reject" && (
                          <>
                            <dt className="text-muted-foreground">
                              {turn.supplier_action === "accept"
                                ? "Agreed price:"
                                : "Counter price:"}
                            </dt>
                            <dd className="tabular-nums font-medium">
                              {inr(turn.supplier_price)}
                            </dd>
                          </>
                        )}
                        <dt className="text-muted-foreground">Delivery offer:</dt>
                        <dd className="tabular-nums">
                          {fmtDate(turn.proposed_delivery_date)}
                        </dd>
                      </dl>
                      {turn.supplier_message && (
                        <p className="mt-1 flex items-start gap-1.5 text-sm text-muted-foreground">
                          <ScanText
                            className="mt-0.5 h-3.5 w-3.5 shrink-0"
                            aria-hidden="true"
                          />
                          <span className="italic">“{turn.supplier_message}”</span>
                        </p>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ol>

            {/* Final outcome */}
            {status === "done" && snapshot && (
              <div
                className={cn(
                  "mt-2 flex items-center gap-3 rounded-md p-3",
                  accepted ? "bg-primary/10 text-foreground" : "bg-muted text-foreground",
                )}
                role="status"
              >
                <CheckCircle2
                  className="h-5 w-5 text-primary shrink-0"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-sm font-semibold">
                    {accepted
                      ? "Deal agreed"
                      : `Outcome: ${snapshot.final_outcome ?? "closed"}`}
                  </p>
                  {accepted && (
                    <p className="text-sm text-muted-foreground">
                      Settled at{" "}
                      <span className="tabular-nums font-semibold text-foreground">
                        {inr(agreedPrice)}
                      </span>{" "}
                      per unit, delivery by{" "}
                      <span className="tabular-nums font-semibold text-foreground">
                        {fmtDate(agreedDeliveryDate ?? snapshot.agreed_delivery_date)}
                      </span>{" "}
                      over {snapshot.rounds_elapsed} round
                      {snapshot.rounds_elapsed === 1 ? "" : "s"}.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Flow controls */}
            {accepted && onProceed && (
              <Button
                onClick={() =>
                  onProceed({
                    price: agreedPrice,
                    deliveryDate: agreedDeliveryDate ?? snapshot?.agreed_delivery_date ?? null,
                  })
                }
              >
                Proceed to Order
              </Button>
            )}
            {rejected && onReject && (
              <Button variant="outline" onClick={onReject}>
                <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
                Back to Compare
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  )
}

function SupplierActionBadge({
  action,
  source,
}: {
  action: "accept" | "counter" | "reject"
  source: "llm" | "fallback"
}) {
  const variant =
    action === "accept"
      ? "default"
      : action === "reject"
        ? "destructive"
        : "secondary"
  return (
    <span className="flex items-center gap-1.5">
      <Badge variant={variant}>{action}</Badge>
      {source === "fallback" && (
        <Badge variant="outline" className="text-xs">
          fallback
        </Badge>
      )}
    </span>
  )
}

export default NegotiationStepper
