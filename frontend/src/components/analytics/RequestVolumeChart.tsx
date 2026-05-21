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
import { TrendingUp } from "lucide-react"
import type { RequestVolumePoint } from "@/lib/types"

interface Props {
  data: RequestVolumePoint[]
  onPointClick?: (date: string) => void
}

export default function RequestVolumeChart({ data, onPointClick }: Props) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <TrendingUp className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No data for this period</span>
      </div>
    )
  }

  return (
    <div role="img" aria-label="Request volume over time">
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
        <Tooltip formatter={(v: any) => [v, "Requests"]} />
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
    </div>
  )
}
