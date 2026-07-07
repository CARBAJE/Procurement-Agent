"use client"

import { useState } from "react"
import Link from "next/link"
import { Search, PlusCircle, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import type { AnalyticsRequest } from "@/lib/types"

interface StatusConfig {
  label: string
  dotClass: string
  textClass: string
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  confirmed:        { label: "Confirmed",      dotClass: "bg-emerald-500", textClass: "text-emerald-700" },
  pending_approval: { label: "Pend. Approval", dotClass: "bg-amber-500",   textClass: "text-amber-700"  },
  discovering:      { label: "Searching",      dotClass: "bg-blue-400",    textClass: "text-blue-700"   },
  scoring:          { label: "Scoring",        dotClass: "bg-blue-400",    textClass: "text-blue-700"   },
  negotiating:      { label: "Negotiating",    dotClass: "bg-violet-500",  textClass: "text-violet-700" },
  cancelled:        { label: "Cancelled",      dotClass: "bg-rose-500",    textClass: "text-rose-700"   },
  draft:            { label: "Draft",          dotClass: "bg-slate-400",   textClass: "text-slate-600"  },
  parsing:          { label: "Processing",     dotClass: "bg-blue-400",    textClass: "text-blue-700"   },
}

const STATUS_MESSAGE: Record<string, string> = {
  cancelled:        "This request was cancelled. There is no active order to view.",
  pending_approval: "This request is awaiting approval from an approver. Once approved, the order will appear here.",
  draft:            "This request is still a draft and has not been submitted.",
  parsing:          "The agent is still parsing the intent of this request.",
  discovering:      "The agent is searching for matching suppliers on the Beckn network.",
  scoring:          "The agent is scoring and ranking the offers it found.",
  negotiating:      "The agent is negotiating terms with the selected supplier.",
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  })
}

function formatTotalPrice(
  price: number | null,
  quantity: number | null | undefined,
  currency: string,
): string {
  if (price === null) return "—"
  const total = quantity != null && quantity > 0 ? price * quantity : price
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(total)
}

interface RecentRequestsTableProps {
  requests: AnalyticsRequest[]
  onRowClick?: (req: AnalyticsRequest) => void
}

export default function RecentRequestsTable({ requests, onRowClick }: RecentRequestsTableProps) {
  const interactive = Boolean(onRowClick)
  const [query, setQuery]   = useState("")
  const [infoReq, setInfoReq] = useState<AnalyticsRequest | null>(null)

  const filtered = query.trim()
    ? requests.filter(
        (r) =>
          r.raw_input_text.toLowerCase().includes(query.toLowerCase()) ||
          (r.category ?? "").toLowerCase().includes(query.toLowerCase()) ||
          r.status.toLowerCase().includes(query.toLowerCase()),
      )
    : requests

  function activate(req: AnalyticsRequest) {
    if (req.status === "confirmed") onRowClick?.(req)
    else setInfoReq(req)
  }

  return (
    <>
      {/* Search bar */}
      <div className="relative mb-3">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" aria-hidden="true" />
        <Input
          type="search"
          placeholder="Search requests…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pl-8 h-8 text-sm"
          aria-label="Search recent requests"
        />
      </div>

      {requests.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <p className="text-muted-foreground text-sm">No requests for the selected period.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div role="status" className="flex flex-col items-center justify-center py-8 text-center">
          <p className="text-muted-foreground text-sm">No requests match &ldquo;{query}&rdquo;.</p>
        </div>
      ) : (
        <div className="overflow-x-auto overflow-y-auto max-h-[380px] border rounded-md">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background z-10 border-b">
              <tr>
                <th scope="col" className="text-left py-2 px-3 font-medium text-muted-foreground">Request</th>
                <th scope="col" className="text-left py-2 px-3 font-medium text-muted-foreground">Status</th>
                <th scope="col" className="text-right py-2 px-3 font-medium text-muted-foreground">Total spent</th>
                <th scope="col" className="text-right py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((req) => {
                const cfg = STATUS_CONFIG[req.status] ?? {
                  label:     req.status,
                  dotClass:  "bg-slate-400",
                  textClass: "text-slate-600",
                }
                return (
                  <tr
                    key={req.request_id}
                    onClick={interactive ? () => activate(req) : undefined}
                    onKeyDown={
                      interactive
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              activate(req)
                            }
                          }
                        : undefined
                    }
                    tabIndex={interactive ? 0 : undefined}
                    role={interactive ? "button" : undefined}
                    aria-label={
                      interactive
                        ? req.status === "confirmed"
                          ? `Open order for: ${req.raw_input_text}`
                          : `Show status for: ${req.raw_input_text}`
                        : undefined
                    }
                    className={cn(
                      "border-b last:border-0 transition-colors",
                      interactive
                        ? "cursor-pointer hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                        : "hover:bg-muted/50",
                    )}
                  >
                    <td className="py-2.5 px-3 max-w-[200px]">
                      <p className="truncate font-medium text-sm" title={req.raw_input_text}>
                        {req.raw_input_text}
                      </p>
                      {req.category && (
                        <p className="text-xs text-muted-foreground mt-0.5">{req.category}</p>
                      )}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={cn("h-2 w-2 rounded-full shrink-0", cfg.dotClass)}
                          aria-hidden="true"
                        />
                        <span className={cn("text-xs font-medium", cfg.textClass)}>{cfg.label}</span>
                      </div>
                      {req.user_overridden === true && (
                        <p className="text-[10px] text-orange-500 font-medium mt-0.5 pl-3.5">Modified</p>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono text-xs">
                      {formatTotalPrice(req.agreed_price, req.quantity, req.currency)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-muted-foreground text-xs whitespace-nowrap">
                      {formatDate(req.created_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Non-confirmed request info modal */}
      <Dialog open={infoReq !== null} onOpenChange={(open) => { if (!open) setInfoReq(null) }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Info className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
              Request Status
            </DialogTitle>
          </DialogHeader>

          {infoReq && (() => {
            const cfg = STATUS_CONFIG[infoReq.status]
            const isCancelled = infoReq.status === "cancelled"
            return (
              <div className="space-y-4">
                {/* Status indicator */}
                <div className="flex items-center gap-2">
                  <span className={cn("h-2.5 w-2.5 rounded-full shrink-0", cfg?.dotClass ?? "bg-slate-400")} aria-hidden="true" />
                  <span className={cn("text-sm font-semibold", cfg?.textClass ?? "text-slate-600")}>
                    {cfg?.label ?? infoReq.status}
                  </span>
                  {infoReq.user_overridden && (
                    <span className="text-xs text-orange-500 font-medium">(Modified)</span>
                  )}
                </div>

                {/* Request detail card */}
                <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
                  <p className="text-sm font-medium leading-relaxed">{infoReq.raw_input_text}</p>
                  <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                    {infoReq.category && (
                      <span>
                        <span className="font-medium text-foreground">Category: </span>
                        {infoReq.category}
                      </span>
                    )}
                    <span>
                      <span className="font-medium text-foreground">Submitted: </span>
                      {formatDate(infoReq.created_at)}
                    </span>
                    {infoReq.agreed_price != null && (
                      <span>
                        <span className="font-medium text-foreground">Agreed price: </span>
                        {formatTotalPrice(infoReq.agreed_price, infoReq.quantity, infoReq.currency)}
                      </span>
                    )}
                  </div>
                </div>

                {/* Explanation */}
                <div className="rounded-lg border bg-card p-3 space-y-2 text-sm">
                  <p className="text-muted-foreground">
                    {STATUS_MESSAGE[infoReq.status] ?? "This request has no confirmed order yet."}
                  </p>
                </div>
              </div>
            )
          })()}

          <DialogFooter className="flex flex-col-reverse sm:flex-row gap-2 mt-2">
            <Button variant="outline" onClick={() => setInfoReq(null)}>Close</Button>
            {infoReq?.status !== "cancelled" && (
              <Button asChild onClick={() => setInfoReq(null)}>
                <Link href="/request/new">
                  <PlusCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                  Start new request
                </Link>
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
