"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { BarChart2 } from "lucide-react"
import type { CycleTimeCategory } from "@/lib/types"

interface CycleTimeBarChartProps {
  data: CycleTimeCategory[]
  onBarClick?: (category: string) => void
}

export default function CycleTimeBarChart({ data, onBarClick }: CycleTimeBarChartProps) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[300px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <BarChart2 className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
      </div>
    )
  }

  return (
    <div role="img" aria-label="Cycle time reduction by category: before vs. with agent">
    <ResponsiveContainer width="100%" height={300}>
      <BarChart
        data={data}
        onClick={
          onBarClick
            ? (e) => { if (e?.activeLabel) onBarClick(String(e.activeLabel)) }
            : undefined
        }
        style={{ cursor: onBarClick ? "pointer" : undefined }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="category" tick={{ fontSize: 10 }} />
        <YAxis unit="h" tick={{ fontSize: 11 }} />
        <Tooltip
          formatter={(v, name) => [
            `${Number(v ?? 0)}h`,
            name === "before_hours" ? "Before agent" : "With agent",
          ]}
        />
        <Legend
          formatter={(v: string) =>
            v === "before_hours" ? "Before agent" : "With agent"
          }
        />
        <Bar dataKey="before_hours" fill="#f97316" radius={[4, 4, 0, 0]} />
        <Bar dataKey="after_hours"  fill="#3b82f6" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
    </div>
  )
}
