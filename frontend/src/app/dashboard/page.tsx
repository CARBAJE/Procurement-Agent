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
  DollarSign,
  PlusCircle,
  RefreshCw,
  Settings,
  Users,
  Zap,
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import DrillDownModal, {
  type DrillDownColumn,
  type DrillDownRow,
} from "@/components/analytics/DrillDownModal"
import { fetchAnalytics, fetchBenchmark, fetchBusinessImpact } from "@/lib/api"
import type { AnalyticsData, AnalyticsPeriod, BenchmarkReport, BusinessImpact } from "@/lib/types"

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

const PERIODS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "30d",  label: "30 days" },
  { value: "90d",  label: "90 days" },
  { value: "180d", label: "180 days" },
]

// Drill-down column configs ──────────────────────────────────────────────────

const COLS_REQUEST: DrillDownColumn[] = [
  {
    key: "raw_input_text",
    label: "Request",
    render: (v) => (
      <span className="block max-w-xs truncate" title={String(v ?? "")}>
        {String(v ?? "")}
      </span>
    ),
  },
  {
    key: "status",
    label: "Status",
    render: (v) => (
      <Badge variant="outline" className="text-xs capitalize">
        {String(v ?? "")}
      </Badge>
    ),
  },
  {
    key: "agreed_price",
    label: "Price",
    render: (v) =>
      v != null ? `₹${Number(v).toLocaleString("en-IN")}` : "—",
  },
  {
    key: "created_at",
    label: "Date",
    render: (v) =>
      new Date(String(v ?? "")).toLocaleDateString("en-US", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
  },
]

const COLS_REQUEST_WITH_CAT: DrillDownColumn[] = [
  COLS_REQUEST[0],
  { key: "category", label: "Category", render: (v) => String(v ?? "—") },
  COLS_REQUEST[1],
  COLS_REQUEST[2],
  COLS_REQUEST[3],
]

const COLS_SUPPLIER: DrillDownColumn[] = [
  { key: "metric", label: "Metric" },
  {
    key: "score",
    label: "Score",
    render: (v, row) =>
      row.metric === "Total orders"
        ? String(v)
        : `${v} / 100`,
  },
]

const COLS_SUPPLIERS_RANKED: DrillDownColumn[] = [
  { key: "provider_name", label: "Provider" },
  { key: "total_orders",  label: "Orders", render: (v) => String(v ?? 0) },
  { key: "quality_score", label: "Quality", render: (v) => `${v} / 100` },
  { key: "delivery_score", label: "Delivery", render: (v) => `${v} / 100` },
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
          aria-pressed={value === p.value}
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
      <main id="main-content" className="container py-8">
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

interface DrillDownLevel {
  title: string
  description?: string
  columns: DrillDownColumn[]
  rows: DrillDownRow[]
  onRowClick?: (row: DrillDownRow) => void
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter()
  const { data: session, status } = useSession()

  const [period, setPeriod]       = useState<AnalyticsPeriod>("90d")
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [drillStack, setDrillStack] = useState<DrillDownLevel[]>([])
  const [benchmark, setBenchmark]         = useState<BenchmarkReport | null>(null)
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)
  const [benchmarkError, setBenchmarkError] = useState<string | null>(null)
  const [teamSizeFte, setTeamSizeFte] = useState(5)
  const [businessImpact, setBusinessImpact] = useState<BusinessImpact>({
    platform_licensing: { baseline_monthly: 50_000, actual_monthly: 50_000 },
    team_productivity:  { requests_per_fte_before: 12, requests_per_fte_after: 12 },
    audit_prep_hours:   { before: 40, after: 40 },
  })

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login")
  }, [status, router])

  useEffect(() => {
    if (status !== "authenticated") return
    setLoading(true)
    setFetchError(false)
    fetchAnalytics(period)
      .then((data) => { setAnalytics(data); setFetchError(false) })
      .catch(() => { setAnalytics(null); setFetchError(true) })
      .finally(() => setLoading(false))
  }, [period, status])

  // Populate Business Impact "after" values from real DB data when available.
  // Baselines stay user-configurable; only the "actual" side is overwritten.
  useEffect(() => {
    if (status !== "authenticated") return
    fetchBusinessImpact(period)
      .then((live) => {
        setBusinessImpact((prev) => ({
          platform_licensing: {
            ...prev.platform_licensing,
            actual_monthly: Math.max(
              0,
              prev.platform_licensing.baseline_monthly - live.monthly_savings,
            ),
          },
          team_productivity: {
            ...prev.team_productivity,
            requests_per_fte_after: Math.max(
              prev.team_productivity.requests_per_fte_before + 1,
              Math.round(live.requests_this_month / teamSizeFte),
            ),
          },
          audit_prep_hours: {
            ...prev.audit_prep_hours,
            after: Math.max(
              1,
              Math.round(prev.audit_prep_hours.before * (live.avg_cycle_time_hours / 72.0)),
            ),
          },
        }))
      })
      .catch(() => { /* keep defaults on unavailable analytics */ })
  }, [period, status, teamSizeFte])

  if (status === "loading" || (status === "authenticated" && loading)) {
    return <DashboardSkeleton />
  }
  if (!session) return null

  if (fetchError) {
    return (
      <>
        <Navbar />
        <main id="main-content" className="container py-8 flex items-center justify-center min-h-[60vh]">
          <div className="flex flex-col items-center gap-4 text-center max-w-sm">
            <AlertCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
            <h1 className="text-lg font-semibold">Failed to load analytics</h1>
            <p className="text-sm text-muted-foreground">
              Could not reach the analytics service. Check your connection or try again.
            </p>
            <Button
              onClick={() => {
                setFetchError(false)
                setLoading(true)
                fetchAnalytics(period)
                  .then((data) => { setAnalytics(data); setFetchError(false) })
                  .catch(() => { setAnalytics(null); setFetchError(true) })
                  .finally(() => setLoading(false))
              }}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          </div>
        </main>
      </>
    )
  }

  // ── Drill-down handlers ────────────────────────────────────────────────────

  function openDrill(level: DrillDownLevel) {
    setDrillStack([level])
  }

  function pushDrill(level: DrillDownLevel) {
    setDrillStack((s) => [...s, level])
  }

  function popDrill() {
    setDrillStack((s) => s.slice(0, -1))
  }

  function closeDrill() {
    setDrillStack([])
  }

  function navigateToRequest(row: DrillDownRow) {
    const txnId = String(row.request_id ?? "")
    if (!txnId) return
    closeDrill()
    router.push(`/request/${encodeURIComponent(txnId)}/order`)
  }

  function supplierDetailLevel(name: string): DrillDownLevel | null {
    const s = (analytics?.supplier_metrics ?? []).find(
      (m) => m.provider_name === name,
    )
    if (!s) return null
    return {
      title: `Supplier: ${name}`,
      columns: COLS_SUPPLIER,
      rows: [
        { metric: "Quality",      score: s.quality_score },
        { metric: "Delivery",     score: s.delivery_score },
        { metric: "Price",        score: s.price_competitiveness },
        { metric: "Compliance",   score: s.compliance_score },
        { metric: "Total orders", score: s.total_orders },
      ],
    }
  }

  function openCategoryDrillDown(category: string) {
    const rows = ([...(analytics?.supplier_metrics ?? [])]
      .sort((a, b) => b.total_orders - a.total_orders)
    ) as unknown as DrillDownRow[]
    openDrill({
      title: `Top suppliers — ${category}`,
      description: "Ranked by total orders. Click a provider for full scorecard.",
      columns: COLS_SUPPLIERS_RANKED,
      rows,
      onRowClick: (row) => {
        const next = supplierDetailLevel(String(row.provider_name))
        if (next) pushDrill(next)
      },
    })
  }

  function openDateDrillDown(dateLabel: string) {
    const weekStart = new Date(`${dateLabel} ${new Date().getFullYear()}`)
    const weekEnd   = new Date(weekStart.getTime() + 7 * 24 * 60 * 60 * 1000)
    const rows = (analytics?.recent_requests ?? []).filter((r) => {
      const d = new Date(r.created_at)
      return d >= weekStart && d < weekEnd
    }) as unknown as DrillDownRow[]
    openDrill({
      title: `Week of ${dateLabel}`,
      description: "Click a row to open the order.",
      columns: COLS_REQUEST_WITH_CAT,
      rows,
      onRowClick: navigateToRequest,
    })
  }

  function openStatusDrillDown(status: string) {
    const rows = (analytics?.recent_requests ?? []).filter(
      (r) => r.status === status,
    ) as unknown as DrillDownRow[]
    const statusLabel = status.replace(/_/g, " ")
    openDrill({
      title: `Status: ${statusLabel}`,
      description: "Click a row to open the order.",
      columns: COLS_REQUEST_WITH_CAT,
      rows,
      onRowClick: navigateToRequest,
    })
  }

  function openSupplierDrillDown(name: string) {
    const next = supplierDetailLevel(name)
    if (next) openDrill(next)
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8">

        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
          <div>
            <span className="text-xs font-black tracking-[0.2em] uppercase text-primary block mb-1">
              Procurement Intelligence
            </span>
            <h1 className="text-4xl font-extrabold tracking-tight">Dashboard</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Welcome, {session.user.name}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PeriodToggle value={period} onChange={setPeriod} />
            <Button asChild>
              <Link href="/request/new">
                <PlusCircle className="mr-2 h-4 w-4" />
                New Request
              </Link>
            </Button>
          </div>
        </div>

        {analytics?.data_source === "mock" && (
          <div className="mb-4">
            <Badge variant="secondary" className="text-xs font-medium">
              Demo data — connect PostgreSQL for live data
            </Badge>
          </div>
        )}

        {/* Row 1 — Operational overview */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Request Funnel</CardTitle>
              <CardDescription>
                Request count by status · click a bar for detail
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
              <CardTitle className="text-base">Agent Acceptance Rate</CardTitle>
              <CardDescription>
                % accepted without changes (target ≥60%) · click a point for detail
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

        {/* Row 2 — Agent ROI */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Cycle Time Reduction</CardTitle>
              <CardDescription>
                Hours — traditional vs. with agent · click a bar for detail
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
              <CardTitle className="text-base">Negotiation Savings</CardTitle>
              <CardDescription>
                Avg. discount by category (target 8–15%) · click for detail
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

        {/* Row 3 — Financial overview */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Spend &amp; Savings</CardTitle>
              <CardDescription>
                Weekly trend · click a point to see that week&apos;s requests
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
              <CardTitle className="text-base">Spend by Category</CardTitle>
              <CardDescription>
                Total spend distribution · click a slice for detail
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

        {/* Row 4 — Ecosystem */}
        <div className="grid gap-6 md:grid-cols-2 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Supplier Performance</CardTitle>
              <CardDescription>
                Top 4 providers (0–100) · click a name for their metrics
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
              <CardTitle className="text-base">Request Volume</CardTitle>
              <CardDescription>
                New requests per week · click a point for detail
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

        {/* Row 5 — Business Impact */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="h-5 w-1 rounded-full bg-primary shrink-0" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">Business Impact vs. Baseline</h2>
            </div>
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm">
                  <Settings className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  Configure Baseline
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-sm">
                <DialogHeader>
                  <DialogTitle>Configure Baselines</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-2">
                  <div className="space-y-1">
                    <Label htmlFor="baseline-licensing">Monthly licensing cost without agent (₹)</Label>
                    <Input
                      id="baseline-licensing"
                      type="number"
                      min={0}
                      value={businessImpact.platform_licensing.baseline_monthly}
                      onChange={(e) => setBusinessImpact((prev) => ({
                        ...prev,
                        platform_licensing: { ...prev.platform_licensing, baseline_monthly: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="baseline-requests-fte">Requests per FTE per month (before)</Label>
                    <Input
                      id="baseline-requests-fte"
                      type="number"
                      min={1}
                      value={businessImpact.team_productivity.requests_per_fte_before}
                      onChange={(e) => setBusinessImpact((prev) => ({
                        ...prev,
                        team_productivity: { ...prev.team_productivity, requests_per_fte_before: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="baseline-audit">Audit prep hours per cycle (before)</Label>
                    <Input
                      id="baseline-audit"
                      type="number"
                      min={1}
                      value={businessImpact.audit_prep_hours.before}
                      onChange={(e) => setBusinessImpact((prev) => ({
                        ...prev,
                        audit_prep_hours: { ...prev.audit_prep_hours, before: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="baseline-fte">Procurement team size (FTEs)</Label>
                    <Input
                      id="baseline-fte"
                      type="number"
                      min={1}
                      value={teamSizeFte}
                      onChange={(e) => setTeamSizeFte(Math.max(1, Number(e.target.value)))}
                    />
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Platform Licensing */}
            <Card>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-primary/10 p-2 text-primary shrink-0">
                    <DollarSign className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground">Platform Licensing</p>
                    <p className="text-3xl font-bold tabular-nums leading-none mt-1">
                      ₹{((businessImpact.platform_licensing.baseline_monthly - businessImpact.platform_licensing.actual_monthly) / 1000).toFixed(0)}K
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">saved / month</p>
                    <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
                      <span>₹{(businessImpact.platform_licensing.baseline_monthly / 1000).toFixed(0)}K baseline</span>
                      <span>→</span>
                      <span className="text-green-600 font-medium">₹{(businessImpact.platform_licensing.actual_monthly / 1000).toFixed(0)}K now</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Team Productivity */}
            <Card>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-primary/10 p-2 text-primary shrink-0">
                    <Users className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground">Team Productivity</p>
                    <p className="text-3xl font-bold tabular-nums leading-none mt-1">
                      {Math.round(((businessImpact.team_productivity.requests_per_fte_after - businessImpact.team_productivity.requests_per_fte_before) / businessImpact.team_productivity.requests_per_fte_before) * 100)}%
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">more requests / FTE</p>
                    <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
                      <span>{businessImpact.team_productivity.requests_per_fte_before} req/FTE before</span>
                      <span>→</span>
                      <span className="text-green-600 font-medium">{businessImpact.team_productivity.requests_per_fte_after} now</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Audit Prep Time */}
            <Card>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-primary/10 p-2 text-primary shrink-0">
                    <Zap className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground">Audit Prep Time</p>
                    <p className="text-3xl font-bold tabular-nums leading-none mt-1">
                      {businessImpact.audit_prep_hours.before - businessImpact.audit_prep_hours.after}h
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">saved per cycle</p>
                    <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
                      <span>{businessImpact.audit_prep_hours.before}h before</span>
                      <span>→</span>
                      <span className="text-green-600 font-medium">{businessImpact.audit_prep_hours.after}h now</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Row 6 — CPO Benchmarking */}
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base">CPO Benchmarking Report</CardTitle>
                <CardDescription>
                  Compare your contracted prices against current market rates
                </CardDescription>
              </div>
              {!benchmark && (
                <Button
                  onClick={() => {
                    setBenchmarkLoading(true)
                    setBenchmarkError(null)
                    fetchBenchmark(period)
                      .then(setBenchmark)
                      .catch(() => setBenchmarkError("Analytics service unavailable. Rebuild the analytics container and retry."))
                      .finally(() => setBenchmarkLoading(false))
                  }}
                  disabled={benchmarkLoading}
                  size="sm"
                >
                  {benchmarkLoading
                    ? <><RefreshCw className="mr-2 h-3.5 w-3.5 animate-spin" aria-hidden="true" />Analyzing…</>
                    : <><BarChart2 className="mr-2 h-3.5 w-3.5" aria-hidden="true" />Run Analysis</>
                  }
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {benchmarkError ? (
              <div className="flex flex-col items-center justify-center py-10 text-center gap-3" role="alert">
                <AlertCircle className="h-8 w-8 text-destructive opacity-60" aria-hidden="true" />
                <p className="text-sm text-destructive max-w-xs">{benchmarkError}</p>
                <Button variant="outline" size="sm" onClick={() => setBenchmarkError(null)}>Dismiss</Button>
              </div>
            ) : !benchmark ? (
              <div className="flex flex-col items-center justify-center py-10 text-center gap-3" role="status">
                <BarChart2 className="h-10 w-10 opacity-20" aria-hidden="true" />
                <p className="text-sm text-muted-foreground max-w-xs">
                  Run an analysis to compare your current contracts against the best available market prices and identify potential savings.
                </p>
              </div>
            ) : benchmark.categories.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-center gap-3" role="status">
                <BarChart2 className="h-10 w-10 opacity-20" aria-hidden="true" />
                <p className="text-sm text-muted-foreground max-w-xs">
                  No procurement data available yet. Complete some orders to see benchmarking results.
                </p>
                <Button variant="ghost" size="sm" onClick={() => setBenchmark(null)}>Reset</Button>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-3 p-3 rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-900">
                  <CheckCircle className="h-5 w-5 text-green-600 shrink-0" aria-hidden="true" />
                  <div>
                    <p className="text-sm font-semibold text-green-800 dark:text-green-300">
                      Projected annual savings: ₹{(benchmark.projected_annual_savings / 100_000).toFixed(1)}L
                    </p>
                    <p className="text-xs text-green-700 dark:text-green-400">
                      Across {benchmark.categories.length} categories · Generated {new Date(benchmark.generated_at).toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" })}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() => setBenchmark(null)}
                  >
                    Reset
                  </Button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th scope="col" className="text-left py-2 px-1 font-medium text-muted-foreground">Category</th>
                        <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Contract (₹)</th>
                        <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Best Market (₹)</th>
                        <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Gap</th>
                        <th scope="col" className="text-right py-2 px-1 font-medium text-muted-foreground">Annual Savings</th>
                        <th scope="col" className="text-left py-2 px-1 font-medium text-muted-foreground">Top Alternative</th>
                      </tr>
                    </thead>
                    <tbody>
                      {benchmark.categories.map((row) => (
                        <tr key={row.category} className="border-b last:border-0 hover:bg-muted/50 transition-colors">
                          <td className="py-2 px-1 font-medium">{row.category}</td>
                          <td className="py-2 px-1 text-right tabular-nums">
                            {row.current_contract >= 1000
                              ? `₹${(row.current_contract / 1000).toFixed(0)}K`
                              : `₹${row.current_contract}`}
                          </td>
                          <td className="py-2 px-1 text-right tabular-nums text-green-600">
                            {row.best_market_price >= 1000
                              ? `₹${(row.best_market_price / 1000).toFixed(0)}K`
                              : `₹${row.best_market_price}`}
                          </td>
                          <td className="py-2 px-1 text-right">
                            <Badge variant={row.gap_percent >= 20 ? "destructive" : "secondary"} className="text-xs">
                              -{row.gap_percent}%
                            </Badge>
                          </td>
                          <td className="py-2 px-1 text-right tabular-nums font-medium">
                            {row.annual_savings >= 100_000
                              ? `₹${(row.annual_savings / 100_000).toFixed(1)}L`
                              : `₹${(row.annual_savings / 1000).toFixed(0)}K`}
                          </td>
                          <td className="py-2 px-1 text-muted-foreground text-xs">{row.top_alternative}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {session.user.role !== "requester" && (
          <div className="mt-6">
            <Badge variant="outline" className="text-xs">
              Role: {session.user.role}
            </Badge>
          </div>
        )}
      </main>

      <DrillDownModal
        open={drillStack.length > 0}
        onClose={closeDrill}
        onBack={drillStack.length > 1 ? popDrill : undefined}
        title={drillStack[drillStack.length - 1]?.title ?? ""}
        description={drillStack[drillStack.length - 1]?.description}
        columns={drillStack[drillStack.length - 1]?.columns ?? []}
        rows={drillStack[drillStack.length - 1]?.rows ?? []}
        onRowClick={drillStack[drillStack.length - 1]?.onRowClick}
      />
    </>
  )
}
