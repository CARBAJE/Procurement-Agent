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
import type { SupplierMetric } from "@/lib/types"

interface SupplierRadarChartProps {
  data: SupplierMetric[]
  onSupplierClick?: (name: string) => void
}

const COLORS = ["#3b82f6", "#22c55e", "#f97316", "#a855f7"]

const AXES: { key: keyof SupplierMetric; label: string }[] = [
  { key: "quality_score",         label: "Calidad" },
  { key: "delivery_score",        label: "Entrega" },
  { key: "price_competitiveness", label: "Precio" },
  { key: "compliance_score",      label: "Cumplimiento" },
]

export default function SupplierRadarChart({ data, onSupplierClick }: SupplierRadarChartProps) {
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
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={radarData}>
        <PolarGrid />
        <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12 }} />
        <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 9 }} />
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
  )
}
