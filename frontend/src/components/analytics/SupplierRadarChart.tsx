"use client"

import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts"
import { BarChart2 } from "lucide-react"
import type { SupplierMetric } from "@/lib/types"

interface SupplierRadarChartProps {
  data: SupplierMetric[]
  onSupplierClick?: (name: string) => void
}

const COLORS = ["#3b82f6", "#22c55e", "#f97316", "#a855f7"]

const AXES: { key: keyof SupplierMetric; label: string }[] = [
  { key: "quality_score",         label: "Quality" },
  { key: "delivery_score",        label: "Delivery" },
  { key: "price_competitiveness", label: "Price" },
  { key: "compliance_score",      label: "Compliance" },
]

export default function SupplierRadarChart({ data, onSupplierClick }: SupplierRadarChartProps) {
  if (!data.length) {
    return (
      <div role="status" className="flex h-[300px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <BarChart2 className="h-8 w-8 opacity-30" aria-hidden="true" />
        <span className="text-sm">No supplier data for this period</span>
      </div>
    )
  }

  const topSuppliers = [...data]
    .sort((a, b) => b.total_orders - a.total_orders)
    .slice(0, 4)

  const radarData = AXES.map(({ key, label }) => {
    const row: Record<string, string | number> = { subject: label }
    topSuppliers.forEach((s) => {
      row[s.provider_name] = s[key] as number
    })
    return row
  })

  return (
    <div role="img" aria-label="Supplier performance radar: quality, delivery, price, compliance">
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={radarData}>
        <PolarGrid />
        <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12 }} />
        <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} />
        {topSuppliers.map((s, i) => (
          <Radar
            key={s.bpp_id}
            name={s.provider_name}
            dataKey={s.provider_name}
            stroke={COLORS[i % COLORS.length]}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.15}
          />
        ))}
        <Legend
          wrapperStyle={{ fontSize: "11px", cursor: onSupplierClick ? "pointer" : undefined }}
          onClick={onSupplierClick ? (e: any) => onSupplierClick(String(e.value)) : undefined}
        />
        <Tooltip />
      </RadarChart>
    </ResponsiveContainer>
    </div>
  )
}
