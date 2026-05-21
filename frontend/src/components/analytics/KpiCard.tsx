import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { TrendingDown, TrendingUp } from "lucide-react"

interface KpiCardProps {
  title: string
  value: string
  subtitle?: string
  trend?: { label: string; positive: boolean }
  icon: React.ReactNode
  onClick?: () => void
}

export default function KpiCard({ title, value, subtitle, trend, icon, onClick }: KpiCardProps) {
  const interactive = Boolean(onClick)

  return (
    <Card
      onClick={onClick}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                onClick!()
              }
            }
          : undefined
      }
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? `${title}: ${value}. Click for breakdown.` : undefined}
      className={cn(
        interactive &&
          "cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <div className="text-muted-foreground">{icon}</div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
        {trend && (
          <div
            className={cn(
              "flex items-center gap-1 mt-1 text-xs font-medium",
              trend.positive ? "text-green-600" : "text-red-500",
            )}
          >
            {trend.positive ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {trend.label}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
