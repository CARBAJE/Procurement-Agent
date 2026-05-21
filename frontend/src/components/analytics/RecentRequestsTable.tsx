"use client"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { AnalyticsRequest } from "@/lib/types"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  confirmed:        { label: "Confirmed",      variant: "default" },
  pending_approval: { label: "Pend. Approval", variant: "secondary" },
  discovering:      { label: "Searching",      variant: "outline" },
  scoring:          { label: "Scoring",        variant: "outline" },
  negotiating:      { label: "Negotiating",    variant: "outline" },
  cancelled:        { label: "Cancelled",      variant: "destructive" },
  draft:            { label: "Draft",          variant: "outline" },
  parsing:          { label: "Processing",     variant: "outline" },
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  })
}

function formatPrice(price: number | null, currency: string): string {
  if (price === null) return "—"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(price)
}

interface RecentRequestsTableProps {
  requests: AnalyticsRequest[]
  onRowClick?: (req: AnalyticsRequest) => void
}

export default function RecentRequestsTable({ requests, onRowClick }: RecentRequestsTableProps) {
  const interactive = Boolean(onRowClick)
  if (requests.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <p className="text-muted-foreground text-sm">
          No requests for the selected period.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th scope="col" className="text-left py-2 px-1 font-medium text-muted-foreground">Request</th>
            <th scope="col" className="text-left py-2 px-1 font-medium text-muted-foreground">Status</th>
            <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Price</th>
            <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Date</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((req) => {
            const cfg = STATUS_CONFIG[req.status] ?? {
              label: req.status,
              variant: "outline" as BadgeVariant,
            }
            return (
              <tr
                key={req.request_id}
                onClick={interactive ? () => onRowClick!(req) : undefined}
                onKeyDown={
                  interactive
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          onRowClick!(req)
                        }
                      }
                    : undefined
                }
                tabIndex={interactive ? 0 : undefined}
                role={interactive ? "button" : undefined}
                aria-label={interactive ? `Open request: ${req.raw_input_text}` : undefined}
                className={cn(
                  "border-b last:border-0 transition-colors",
                  interactive
                    ? "cursor-pointer hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                    : "hover:bg-muted/50",
                )}
              >
                <td className="py-2 px-1 max-w-[200px]">
                  <p className="truncate font-medium" title={req.raw_input_text}>
                    {req.raw_input_text}
                  </p>
                  {req.category && (
                    <p className="text-xs text-muted-foreground">{req.category}</p>
                  )}
                </td>
                <td className="py-2 px-1">
                  <div className="flex flex-col gap-1">
                    <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    {req.user_overridden === true && (
                      <Badge
                        variant="outline"
                        className="text-[10px] border-orange-400 text-orange-500 whitespace-nowrap"
                      >
                        Modified
                      </Badge>
                    )}
                  </div>
                </td>
                <td className="py-2 px-1 text-right font-mono text-xs">
                  {formatPrice(req.agreed_price, req.currency)}
                </td>
                <td className="py-2 px-1 text-right text-muted-foreground text-xs whitespace-nowrap">
                  {formatDate(req.created_at)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
