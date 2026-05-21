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
import { BarChart2 } from "lucide-react"
import type { StatusCount } from "@/lib/types"

interface Props {
  data: StatusCount[]
  onBarClick?: (status: string) => void
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  parsing:          { label: "Processing",      color: "#94a3b8" },
  discovering:      { label: "Searching",       color: "#60a5fa" },
  scoring:          { label: "Scoring",         color: "#6366f1" },
  negotiating:      { label: "Negotiating",     color: "#8b5cf6" },
  pending_approval: { label: "Pend. Approval",  color: "#f97316" },
  confirmed:        { label: "Confirmed",       color: "#22c55e" },
  cancelled:        { label: "Cancelled",       color: "#ef4444" },
}

export default function StatusFunnelChart({ data, onBarClick }: Props) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <BarChart2 className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
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
    <div role="img" aria-label="Request funnel by status">
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
          formatter={(v: any) => [v, "Requests"]}
          labelFormatter={(label) => String(label)}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {chartData.map((d, i) => (
            <Cell key={i} fill={d.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
    </div>
  )
}
