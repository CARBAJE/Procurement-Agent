"use client"

import {
  Circle, CheckCircle2, PackageCheck, Truck, MapPin, Package,
  XCircle, Loader2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { OrderState } from "@/lib/types"

interface Step {
  key: OrderState
  label: string
  icon: React.ElementType
}

// Happy-path order lifecycle as rendered on the timeline.
const HAPPY_PATH: Step[] = [
  { key: "CREATED",          label: "Created",          icon: Circle        },
  { key: "ACCEPTED",         label: "Accepted",         icon: CheckCircle2  },
  { key: "PACKED",           label: "Packed",           icon: Package       },
  { key: "SHIPPED",          label: "Shipped",          icon: PackageCheck  },
  { key: "OUT_FOR_DELIVERY", label: "Out for delivery", icon: Truck         },
  { key: "DELIVERED",        label: "Delivered",        icon: MapPin        },
]

const ORDER: Record<OrderState, number> = {
  CREATED: 0,
  ACCEPTED: 1,
  PACKED: 2,
  SHIPPED: 3,
  OUT_FOR_DELIVERY: 4,
  DELIVERED: 5,
  CANCELLED: 99,
}

interface OrderLifecycleTimelineProps {
  state: OrderState | null
  polling?: boolean
}

export default function OrderLifecycleTimeline({ state, polling }: OrderLifecycleTimelineProps) {
  // Cancelled is a terminal "off-path" state — render the whole timeline as
  // inactive + a cancellation indicator.
  if (state === "CANCELLED") {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <XCircle className="h-4 w-4 text-destructive" />
            Order Lifecycle
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">This order has been cancelled.</p>
        </CardContent>
      </Card>
    )
  }

  const currentIdx = state ? (ORDER[state] ?? 0) : -1

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Truck className="h-4 w-4 text-muted-foreground" />
          Order Lifecycle
          {polling && (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-auto" aria-label="Polling status" />
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="relative space-y-0" aria-label="Order progress">
          {HAPPY_PATH.map((step, i) => {
            const Icon = step.icon
            const isLast    = i === HAPPY_PATH.length - 1
            const isCurrent = i === currentIdx
            const isDone    = i < currentIdx
            const isFuture  = i > currentIdx

            const ring =
              isCurrent ? "bg-primary text-primary-foreground ring-4 ring-primary/20" :
              isDone    ? "bg-primary/90 text-primary-foreground" :
                          "bg-muted text-muted-foreground"

            return (
              <li key={step.key} className="flex gap-3" aria-current={isCurrent ? "step" : undefined}>
                <div className="flex flex-col items-center" aria-hidden="true">
                  <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", ring)}>
                    <Icon className="h-4 w-4" />
                  </div>
                  {!isLast && (
                    <div
                      className={cn(
                        "w-px flex-1 my-1",
                        isDone ? "bg-primary" : "bg-border",
                      )}
                    />
                  )}
                </div>
                <div className="pb-4 pt-1 min-w-0 flex-1">
                  <p className={cn(
                    "text-sm font-medium leading-tight",
                    isFuture && "text-muted-foreground",
                  )}>
                    {step.label}
                  </p>
                  {isCurrent && (
                    <p className="text-xs text-primary mt-0.5">Current status</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}
