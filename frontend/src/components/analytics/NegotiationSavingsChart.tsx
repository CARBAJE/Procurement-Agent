"use client"

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  LabelList,
} from "recharts"
import type { NegotiationSaving } from "@/lib/types"

interface Props {
  data: NegotiationSaving[]
  onBarClick?: (category: string) => void
}

function formatINR(value: number): string {
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`
  if (value >= 1_000)   return `₹${(value / 1_000).toFixed(1)}K`
  return `₹${value.toLocaleString("en-IN")}`
}

export default function NegotiationSavingsChart({ data, onBarClick }: Props) {
  if (!data.length) {
    return (
      <div className="flex h-[300px] items-center justify-center text-muted-foreground text-sm">
        Sin datos
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 48, bottom: 8, left: 8 }}
        onClick={onBarClick ? (e) => { if (e?.activeLabel) onBarClick(String(e.activeLabel)) } : undefined}
        style={{ cursor: onBarClick ? "pointer" : undefined }}
      >
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 20]}
          tickFormatter={(v) => `${v}%`}
          tick={{ fontSize: 11 }}
        />
        <YAxis
          type="category"
          dataKey="category"
          width={110}
          tick={{ fontSize: 11 }}
        />
        <Tooltip
          formatter={(value: any, _name: any, props: any) => [
            `${Number(value).toFixed(1)}% descuento — ${formatINR(props.payload.total_savings)} ahorrado`,
            "Negociación",
          ]}
        />
        {/* Document target: 8-15% avg savings */}
        <ReferenceLine
          x={8}
          stroke="hsl(var(--muted-foreground))"
          strokeDasharray="4 4"
          label={{ value: "objetivo 8%", position: "top", fontSize: 10 }}
        />
        <Bar dataKey="avg_discount_percent" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]}>
          <LabelList
            dataKey="avg_discount_percent"
            position="right"
            formatter={(v: any) => `${Number(v).toFixed(1)}%`}
            style={{ fontSize: 11 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
