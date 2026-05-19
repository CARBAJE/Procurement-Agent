"use client"

import { Badge } from "@/components/ui/badge"
import type { AnalyticsRequest } from "@/lib/types"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  confirmed:        { label: "Confirmado",       variant: "default" },
  pending_approval: { label: "Pend. Aprobación", variant: "secondary" },
  discovering:      { label: "Buscando",         variant: "outline" },
  scoring:          { label: "Evaluando",        variant: "outline" },
  negotiating:      { label: "Negociando",       variant: "outline" },
  cancelled:        { label: "Cancelado",        variant: "destructive" },
  draft:            { label: "Borrador",         variant: "outline" },
  parsing:          { label: "Procesando",       variant: "outline" },
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("es-MX", {
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
}

export default function RecentRequestsTable({ requests }: RecentRequestsTableProps) {
  if (requests.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <p className="text-muted-foreground text-sm">
          Sin solicitudes en el período seleccionado.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-left py-2 px-1 font-medium text-muted-foreground">Solicitud</th>
            <th className="text-left py-2 px-1 font-medium text-muted-foreground">Estado</th>
            <th className="text-right py-2 px-1 font-medium text-muted-foreground">Precio</th>
            <th className="text-right py-2 px-1 font-medium text-muted-foreground">Fecha</th>
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
                className="border-b last:border-0 hover:bg-muted/50 transition-colors"
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
                        Modificado
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
