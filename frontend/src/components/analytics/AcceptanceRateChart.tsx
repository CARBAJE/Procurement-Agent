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
import type { AcceptancePoint } from "@/lib/types"

interface Props {
  data: AcceptancePoint[]
  onPointClick?: (date: string) => void
}

export default function AcceptanceRateChart({ data, onPointClick }: Props) {
  if (!data.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-muted-foreground text-sm">
        Sin datos
      </div>
    )
  }

  return (
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
              return [`${Number(value).toFixed(1)}%`, "Recomendaciones aceptadas"]
            return [value, name]
          }}
          labelFormatter={(label) => `Semana del ${label}`}
          contentStyle={{ fontSize: 12 }}
        />
        {/* Document §8.3: target acceptance rate ≥ 60% at 6 months */}
        <ReferenceLine
          y={60}
          stroke="hsl(var(--muted-foreground))"
          strokeDasharray="4 4"
          label={{ value: "objetivo 60%", position: "insideTopRight", fontSize: 10 }}
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
  )
}
