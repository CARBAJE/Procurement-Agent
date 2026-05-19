"use client"

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import type { RequestVolumePoint } from "@/lib/types"

interface Props {
  data: RequestVolumePoint[]
  onPointClick?: (date: string) => void
}

export default function RequestVolumeChart({ data, onPointClick }: Props) {
  if (!data.length) {
    return (
      <div className="flex h-[260px] items-center justify-center text-muted-foreground text-sm">
        Sin datos
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart
        data={data}
        margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
        onClick={onPointClick ? (e) => { if (e?.activeLabel) onPointClick(String(e.activeLabel)) } : undefined}
        style={{ cursor: onPointClick ? "pointer" : undefined }}
      >
        <defs>
          <linearGradient id="volumeGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="hsl(var(--primary))" stopOpacity={0.25} />
            <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}    />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={24}
        />
        <Tooltip formatter={(v: any) => [v, "Solicitudes"]} />
        <Area
          type="monotone"
          dataKey="count"
          stroke="hsl(var(--primary))"
          strokeWidth={2}
          fill="url(#volumeGradient)"
          dot={{ r: 3, fill: "hsl(var(--primary))" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
