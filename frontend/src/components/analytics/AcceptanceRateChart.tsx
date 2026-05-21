"use client"

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts"
import { TrendingUp } from "lucide-react"
import type { AcceptancePoint } from "@/lib/types"

interface Props {
  data: AcceptancePoint[]
  onPointClick?: (date: string) => void
}

export default function AcceptanceRateChart({ data, onPointClick }: Props) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <TrendingUp className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
      </div>
    )
  }

  return (
    <div role="img" aria-label="Agent acceptance rate over time">
    <ResponsiveContainer width="100%" height={260}>
      <LineChart
        data={data}
        margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
        onClick={
          onPointClick
            ? (e) => { if (e?.activeLabel) onPointClick(String(e.activeLabel)) }
            : undefined
        }
        style={{ cursor: onPointClick ? "pointer" : undefined }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} />
        <YAxis
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={36}
        />
        <Tooltip
          formatter={(value: any, name: any) => {
            if (name === "accepted_pct")
              return [`${Number(value).toFixed(1)}%`, "Accepted recommendations"]
            return [value, name]
          }}
          labelFormatter={(label) => `Week of ${label}`}
          contentStyle={{ fontSize: 12 }}
        />
        {/* Document §8.3: target acceptance rate ≥ 60% at 6 months */}
        <ReferenceLine
          y={60}
          stroke="hsl(var(--muted-foreground))"
          strokeDasharray="4 4"
          label={{ value: "target 60%", position: "insideTopRight", fontSize: 11 }}
        />
        <Line
          type="monotone"
          dataKey="accepted_pct"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ r: 3, fill: "#22c55e" }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
    </div>
  )
}
