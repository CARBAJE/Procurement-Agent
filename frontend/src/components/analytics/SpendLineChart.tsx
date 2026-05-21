"use client"

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { TrendingUp } from "lucide-react"
import type { SpendDataPoint } from "@/lib/types"

interface SpendLineChartProps {
  data: SpendDataPoint[]
  onPointClick?: (date: string) => void
}

function tickFormatter(v: number): string {
  if (v >= 100000) return `₹${(v / 100000).toFixed(1)}L`
  if (v >= 1000)   return `₹${(v / 1000).toFixed(0)}K`
  return `₹${v}`
}

export default function SpendLineChart({ data, onPointClick }: SpendLineChartProps) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[300px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <TrendingUp className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
      </div>
    )
  }

  return (
    <div role="img" aria-label="Spend and savings trend over time">
    <ResponsiveContainer width="100%" height={300}>
      <LineChart
        data={data}
        onClick={
          onPointClick
            ? (e) => { if (e?.activeLabel) onPointClick(String(e.activeLabel)) }
            : undefined
        }
        style={{ cursor: onPointClick ? "pointer" : undefined }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={tickFormatter} tick={{ fontSize: 11 }} width={58} />
        <Tooltip
          formatter={(value, name) => [
            `₹${Number(value ?? 0).toLocaleString("en-IN")}`,
            name === "spend" ? "Spend" : "Savings",
          ]}
        />
        <Legend
          formatter={(v: string) => (v === "spend" ? "Spend" : "Savings")}
        />
        <Line
          type="monotone"
          dataKey="spend"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="savings"
          stroke="#22c55e"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
    </div>
  )
}
