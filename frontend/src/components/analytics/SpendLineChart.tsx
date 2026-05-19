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
  return (
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
            name === "spend" ? "Gasto" : "Ahorro",
          ]}
        />
        <Legend
          formatter={(v: string) => (v === "spend" ? "Gasto" : "Ahorro")}
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
  )
}
