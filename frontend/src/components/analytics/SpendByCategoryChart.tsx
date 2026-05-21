"use client"

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { BarChart2 } from "lucide-react"
import type { SpendByCategory } from "@/lib/types"

const COLORS = ["#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ef4444"]

function formatINR(value: number): string {
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`
  if (value >= 1_000)   return `₹${(value / 1_000).toFixed(1)}K`
  return `₹${value.toLocaleString("en-IN")}`
}

interface Props {
  data: SpendByCategory[]
  onSliceClick?: (category: string) => void
}

export default function SpendByCategoryChart({ data, onSliceClick }: Props) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[300px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <BarChart2 className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
      </div>
    )
  }

  return (
    <div role="img" aria-label="Spend distribution by category">
    <ResponsiveContainer width="100%" height={300}>
      <PieChart>
        <Pie
          data={data}
          dataKey="spend"
          nameKey="category"
          cx="45%"
          cy="50%"
          innerRadius={72}
          outerRadius={110}
          paddingAngle={3}
          strokeWidth={0}
          onClick={onSliceClick ? (d: any) => onSliceClick(d.name ?? d.category) : undefined}
          style={{ cursor: onSliceClick ? "pointer" : undefined }}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value: any, name: any) => [formatINR(Number(value)), name]}
        />
        <Legend
          layout="vertical"
          align="right"
          verticalAlign="middle"
          formatter={(value, entry: any) => {
            const pct = entry?.payload?.percent
            return pct != null
              ? `${value} (${(pct * 100).toFixed(0)}%)`
              : String(value)
          }}
        />
      </PieChart>
    </ResponsiveContainer>
    </div>
  )
}
