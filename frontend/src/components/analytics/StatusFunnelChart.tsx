"use client"

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from "recharts"
import type { StatusCount } from "@/lib/types"

interface Props {
  data: StatusCount[]
  onBarClick?: (status: string) => void
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  parsing:          { label: "Procesando",       color: "#94a3b8" },
  discovering:      { label: "Buscando",         color: "#60a5fa" },
  scoring:          { label: "Evaluando",        color: "#6366f1" },
  negotiating:      { label: "Negociando",       color: "#8b5cf6" },
  pending_approval: { label: "Pend. Aprobación", color: "#f97316" },
  confirmed:        { label: "Confirmadas",      color: "#22c55e" },
  cancelled:        { label: "Canceladas",       color: "#ef4444" },
}

export default function StatusFunnelChart({ data, onBarClick }: Props) {
  if (!data.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-muted-foreground text-sm">
        Sin datos
      </div>
    )
  }

  const chartData = data.map((d) => ({
    status: d.status,
    count:  d.count,
    label:  STATUS_CONFIG[d.status]?.label ?? d.status,
    color:  STATUS_CONFIG[d.status]?.color ?? "#94a3b8",
  }))

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 4, right: 48, bottom: 4, left: 8 }}
        onClick={
          onBarClick
            ? (e: any) => {
                const status = e?.activePayload?.[0]?.payload?.status
                if (status) onBarClick(String(status))
              }
            : undefined
        }
        style={{ cursor: onBarClick ? "pointer" : undefined }}
      >
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} tickLine={false} />
        <YAxis
          type="category"
          dataKey="label"
          width={130}
          tick={{ fontSize: 11 }}
          tickLine={false}
        />
        <Tooltip
          formatter={(v: any) => [v, "Solicitudes"]}
          labelFormatter={(label) => String(label)}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {chartData.map((d, i) => (
            <Cell key={i} fill={d.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
