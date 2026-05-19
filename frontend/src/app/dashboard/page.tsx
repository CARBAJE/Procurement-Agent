"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import dynamic from "next/dynamic"
import Link from "next/link"
import {
  AlertCircle,
  BarChart2,
  CheckCircle,
  Clock,
  DollarSign,
  PlusCircle,
  TrendingUp,
} from "lucide-react"

import Navbar from "@/components/layout/Navbar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import KpiCard from "@/components/analytics/KpiCard"
import RecentRequestsTable from "@/components/analytics/RecentRequestsTable"
import DrillDownModal, {
  type DrillDownColumn,
  type DrillDownRow,
} from "@/components/analytics/DrillDownModal"
import { fetchAnalytics } from "@/lib/api"
import type { AnalyticsData, AnalyticsPeriod } from "@/lib/types"

// Recharts uses browser APIs — disable SSR for all chart components.
const CycleTimeBarChart = dynamic(
  () => import("@/components/analytics/CycleTimeBarChart"),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full" /> },
)
const NegotiationSavingsChart = dynamic(
  () => import("@/components/analytics/NegotiationSavingsChart"),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full" /> },
)
const SpendLineChart = dynamic(
  () => import("@/components/analytics/SpendLineChart"),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full" /> },
)
const SpendByCategoryChart = dynamic(
  () => import("@/components/analytics/SpendByCategoryChart"),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full" /> },
)
const SupplierRadarChart = dynamic(
  () => import("@/components/analytics/SupplierRadarChart"),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full" /> },
)
const RequestVolumeChart = dynamic(
  () => import("@/components/analytics/RequestVolumeChart"),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full" /> },
)
const StatusFunnelChart = dynamic(
  () => import("@/components/analytics/StatusFunnelChart"),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full" /> },
)
const AcceptanceRateChart = dynamic(
  () => import("@/components/analytics/AcceptanceRateChart"),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full" /> },
)

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatINR(value: number): string {
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`
  if (value >= 1_000)   return `₹${(value / 1_000).toFixed(1)}K`
  return `₹${value.toLocaleString("en-IN")}`
}

const PERIODS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "30d",  label: "30 días" },
  { value: "90d",  label: "90 días" },
  { value: "180d", label: "180 días" },
]

// Drill-down column configs ──────────────────────────────────────────────────

const COLS_REQUEST: DrillDownColumn[] = [
  {
    key: "raw_input_text",
    label: "Solicitud",
    render: (v) => (
      <span className="block max-w-xs truncate" title={String(v ?? "")}>
        {String(v ?? "")}
      </span>
    ),
  },
  {
    key: "status",
    label: "Estado",
    render: (v) => (
      <Badge variant="outline" className="text-xs capitalize">
        {String(v ?? "")}
      </Badge>
    ),
  },
  {
    key: "agreed_price",
    label: "Precio",
    render: (v) =>
      v != null ? `₹${Number(v).toLocaleString("en-IN")}` : "—",
  },
  {
    key: "created_at",
    label: "Fecha",
    render: (v) =>
      new Date(String(v ?? "")).toLocaleDateString("es-MX", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
  },
]

const COLS_REQUEST_WITH_CAT: DrillDownColumn[] = [
  COLS_REQUEST[0],
  { key: "category", label: "Categoría", render: (v) => String(v ?? "—") },
  COLS_REQUEST[1],
  COLS_REQUEST[2],
  COLS_REQUEST[3],
]

const COLS_SUPPLIER: DrillDownColumn[] = [
  { key: "metric", label: "Métrica" },
  {
    key: "score",
    label: "Puntuación",
    render: (v, row) =>
      row.metric === "Total pedidos"
        ? String(v)
        : `${v} / 100`,
  },
]

// ── Period toggle ─────────────────────────────────────────────────────────────

function PeriodToggle({
  value,
  onChange,
}: {
  value: AnalyticsPeriod
  onChange: (p: AnalyticsPeriod) => void
}) {
  return (
    <div className="flex rounded-md border overflow-hidden">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          onClick={() => onChange(p.value)}
          className={`px-3 py-1.5 text-sm font-medium transition-colors ${
            value === p.value
              ? "bg-primary text-primary-foreground"
              : "bg-background text-muted-foreground hover:bg-muted"
          }`}
        >
          {p.label}
        </button>
      ))}
    </div>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <>
      <Navbar />
      <main className="container py-8">
        <div className="flex items-center justify-between mb-8">
          <div className="space-y-2">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-4 w-48" />
          </div>
          <Skeleton className="h-9 w-36" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6">
                <Skeleton className="h-16" />
              </CardContent>
            </Card>
          ))}
        </div>
        {[0, 1, 2].map((row) => (
          <div key={row} className="grid gap-6 md:grid-cols-2 mb-6">
            <Card><CardContent className="pt-6"><Skeleton className="h-[300px]" /></CardContent></Card>
            <Card><CardContent className="pt-6"><Skeleton className="h-[300px]" /></CardContent></Card>
          </div>
        ))}
        <Card><CardContent className="pt-6"><Skeleton className="h-[240px]" /></CardContent></Card>
      </main>
    </>
  )
}

// ── Drill-down state ──────────────────────────────────────────────────────────

interface DrillDownState {
  open: boolean
  title: string
  columns: DrillDownColumn[]
  rows: DrillDownRow[]
}

const CLOSED: DrillDownState = { open: false, title: "", columns: [], rows: [] }

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter()
  const { data: session, status } = useSession()

  const [period, setPeriod]     = useState<AnalyticsPeriod>("90d")
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null)
  const [loading, setLoading]   = useState(true)
  const [drillDown, setDrillDown] = useState<DrillDownState>(CLOSED)

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login")
  }, [status, router])

  useEffect(() => {
    if (status !== "authenticated") return
    setLoading(true)
    fetchAnalytics(period)
      .then(setAnalytics)
      .catch(() => setAnalytics(null))
      .finally(() => setLoading(false))
  }, [period, status])

  if (status === "loading" || (status === "authenticated" && loading)) {
    return <DashboardSkeleton />
  }
  if (!session) return null

  const kpis = analytics?.kpis
  const cycleReduction = kpis
    ? Math.round(
        ((kpis.baseline_cycle_time_hours - kpis.avg_cycle_time_hours) /
          kpis.baseline_cycle_time_hours) * 100,
      )
    : 0

  // ── Drill-down handlers ────────────────────────────────────────────────────

  function openCategoryDrillDown(category: string) {
    const rows = (analytics?.recent_requests ?? []).filter(
      (r) => r.category === category,
    ) as unknown as DrillDownRow[]
    setDrillDown({
      open: true,
      title: `Detalle — ${category}`,
      columns: COLS_REQUEST,
      rows,
    })
  }

  function openDateDrillDown(dateLabel: string) {
    const weekStart = new Date(`${dateLabel} ${new Date().getFullYear()}`)
    const weekEnd   = new Date(weekStart.getTime() + 7 * 24 * 60 * 60 * 1000)
    const rows = (analytics?.recent_requests ?? []).filter((r) => {
      const d = new Date(r.created_at)
      return d >= weekStart && d < weekEnd
    }) as unknown as DrillDownRow[]
    setDrillDown({
      open: true,
      title: `Semana del ${dateLabel}`,
      columns: COLS_REQUEST_WITH_CAT,
      rows,
    })
  }

  function openStatusDrillDown(status: string) {
    const rows = (analytics?.recent_requests ?? []).filter(
      (r) => r.status === status,
    ) as unknown as DrillDownRow[]
    const statusLabel = status.replace(/_/g, " ")
    setDrillDown({
      open: true,
      title: `Estado: ${statusLabel}`,
      columns: COLS_REQUEST_WITH_CAT,
      rows,
    })
  }

  function openSupplierDrillDown(name: string) {
    const s = (analytics?.supplier_metrics ?? []).find(
      (m) => m.provider_name === name,
    )
    if (!s) return
    const rows: DrillDownRow[] = [
      { metric: "Calidad",       score: s.quality_score },
      { metric: "Entrega",       score: s.delivery_score },
      { metric: "Precio",        score: s.price_competitiveness },
      { metric: "Cumplimiento",  score: s.compliance_score },
      { metric: "Total pedidos", score: s.total_orders },
    ]
    setDrillDown({
      open: true,
      title: `Proveedor: ${name}`,
      columns: COLS_SUPPLIER,
      rows,
    })
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
      <Navbar />
      <main className="container py-8">

        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold">Dashboard</h1>
            <p className="text-muted-foreground">
              Bienvenido, {session.user.name}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PeriodToggle value={period} onChange={setPeriod} />
            <Button asChild>
              <Link href="/request/new">
                <PlusCircle className="mr-2 h-4 w-4" />
                Nueva Solicitud
              </Link>
            </Button>
          </div>
        </div>

        {analytics?.data_source === "mock" && (
          <div className="mb-4">
            <Badge variant="outline" className="text-xs text-muted-foreground">
              Datos de demostración — conecta PostgreSQL para datos reales
            </Badge>
          </div>
        )}

        {/* KPI Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
          <KpiCard
            title="Total Gasto"
            value={kpis ? formatINR(kpis.total_spend) : "—"}
            subtitle={`Período: ${period}`}
            icon={<DollarSign className="h-4 w-4" />}
          />
          <KpiCard
            title="Ahorro Total"
            value={kpis ? formatINR(kpis.total_savings) : "—"}
            subtitle={kpis ? `${kpis.savings_percent}% vs precio de mercado` : undefined}
            trend={kpis ? { label: `${kpis.savings_percent}% ahorrado`, positive: true } : undefined}
            icon={<TrendingUp className="h-4 w-4" />}
          />
          <KpiCard
            title="Solicitudes Activas"
            value={kpis ? String(kpis.active_requests) : "—"}
            subtitle="Pendientes de respuesta"
            icon={<Clock className="h-4 w-4" />}
          />
          <KpiCard
            title="Completadas"
            value={kpis ? String(kpis.completed_this_month) : "—"}
            subtitle="Este mes"
            icon={<CheckCircle className="h-4 w-4" />}
          />
          <KpiCard
            title="Ciclo Promedio"
            value={kpis ? `${kpis.avg_cycle_time_hours}h` : "—"}
            subtitle={`vs ${kpis?.baseline_cycle_time_hours ?? 72}h ciclo tradicional`}
            trend={kpis ? { label: `${cycleReduction}% más rápido`, positive: true } : undefined}
            icon={<BarChart2 className="h-4 w-4" />}
          />
          <KpiCard
            title="Pend. Aprobación"
            value={kpis ? String(kpis.pending_approval) : "—"}
            subtitle="Requieren revisión"
            icon={<AlertCircle className="h-4 w-4" />}
          />
        </div>

        {/* Fila 1 — Visión operacional */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Embudo de Solicitudes</CardTitle>
              <CardDescription>
                Distribución de solicitudes por estado · haz clic en una barra para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <StatusFunnelChart
                data={analytics?.status_funnel ?? []}
                onBarClick={openStatusDrillDown}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Tasa de Aceptación del Agente</CardTitle>
              <CardDescription>
                % de recomendaciones aceptadas sin modificar (objetivo: ≥60%) · haz clic en un punto para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AcceptanceRateChart
                data={analytics?.acceptance_rate ?? []}
                onPointClick={openDateDrillDown}
              />
            </CardContent>
          </Card>
        </div>

        {/* Fila 2 — ROI del agente */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Reducción de Ciclo por Categoría</CardTitle>
              <CardDescription>
                Horas — ciclo tradicional vs. con el agente · haz clic en una barra para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CycleTimeBarChart
                data={analytics?.cycle_time_by_category ?? []}
                onBarClick={openCategoryDrillDown}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Ahorro por Negociación</CardTitle>
              <CardDescription>
                Descuento promedio por categoría (objetivo: 8–15%) · haz clic para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <NegotiationSavingsChart
                data={analytics?.negotiation_savings ?? []}
                onBarClick={openCategoryDrillDown}
              />
            </CardContent>
          </Card>
        </div>

        {/* Fila 3 — Visión financiera */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Gasto y Ahorro</CardTitle>
              <CardDescription>
                Evolución semanal · haz clic en un punto para ver las solicitudes de esa semana
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SpendLineChart
                data={analytics?.spend_over_time ?? []}
                onPointClick={openDateDrillDown}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Gasto por Categoría</CardTitle>
              <CardDescription>
                Distribución del gasto total · haz clic en una sección para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SpendByCategoryChart
                data={analytics?.spend_by_category ?? []}
                onSliceClick={openCategoryDrillDown}
              />
            </CardContent>
          </Card>
        </div>

        {/* Fila 4 — Ecosistema */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Rendimiento de Proveedores</CardTitle>
              <CardDescription>
                Top 4 proveedores (0–100) · haz clic en un nombre para ver sus métricas
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SupplierRadarChart
                data={analytics?.supplier_metrics ?? []}
                onSupplierClick={openSupplierDrillDown}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Volumen de Solicitudes</CardTitle>
              <CardDescription>
                Solicitudes nuevas por semana · haz clic en un punto para ver el detalle
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RequestVolumeChart
                data={analytics?.request_volume ?? []}
                onPointClick={openDateDrillDown}
              />
            </CardContent>
          </Card>
        </div>

        {/* Fila 5 — Actividad reciente */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Solicitudes Recientes</CardTitle>
            <CardDescription>
              Últimas solicitudes de compra del período
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RecentRequestsTable requests={analytics?.recent_requests ?? []} />
          </CardContent>
        </Card>

        {session.user.role !== "requester" && (
          <div className="mt-6">
            <Badge variant="outline" className="text-xs">
              Rol: {session.user.role}
            </Badge>
          </div>
        )}
      </main>

      <DrillDownModal
        open={drillDown.open}
        onClose={() => setDrillDown(CLOSED)}
        title={drillDown.title}
        columns={drillDown.columns}
        rows={drillDown.rows}
      />
    </>
  )
}
