"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import Link from "next/link"
import {
  AlertCircle,
  BarChart2,
  CheckCircle,
  Clock,
  DollarSign,
  PlusCircle,
  RefreshCw,
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatINR(value: number): string {
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`
  if (value >= 1_000)   return `₹${(value / 1_000).toFixed(1)}K`
  return `₹${value.toLocaleString("en-IN")}`
}

const PERIODS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "30d",  label: "30 days" },
  { value: "90d",  label: "90 days" },
  { value: "180d", label: "180 days" },
]

// ── Drill-down columns ────────────────────────────────────────────────────────

const COLS_REQUEST_WITH_CAT: DrillDownColumn[] = [
  {
    key: "raw_input_text",
    label: "Request",
    render: (v) => (
      <span className="block max-w-xs truncate" title={String(v ?? "")}>
        {String(v ?? "")}
      </span>
    ),
  },
  { key: "category", label: "Category", render: (v) => String(v ?? "—") },
  { key: "status",   label: "Status",   render: (v) => String(v ?? "").replace(/_/g, " ") },
  {
    key: "agreed_price",
    label: "Price",
    render: (v) => (v != null ? `₹${Number(v).toLocaleString("en-IN")}` : "—"),
  },
  {
    key: "created_at",
    label: "Date",
    render: (v) =>
      new Date(String(v ?? "")).toLocaleDateString("en-US", {
        day: "numeric", month: "short", year: "numeric",
      }),
  },
]

const COLS_SPEND: DrillDownColumn[] = [
  { key: "category", label: "Category" },
  { key: "spend",    label: "Spend",      render: (v) => formatINR(Number(v)) },
  { key: "pct",      label: "% of Total", render: (v) => `${v}%` },
]

const COLS_NEGOTIATION: DrillDownColumn[] = [
  { key: "category", label: "Category" },
  { key: "avg_discount_percent", label: "Avg Discount", render: (v) => `${v}%` },
  { key: "total_savings",        label: "Savings",      render: (v) => formatINR(Number(v)) },
]

const COLS_CYCLE: DrillDownColumn[] = [
  { key: "category",     label: "Category" },
  { key: "before_hours", label: "Traditional", render: (v) => `${v}h` },
  { key: "after_hours",  label: "With Agent",  render: (v) => `${v}h` },
  { key: "reduction",    label: "Reduction",   render: (v) => `${v}%` },
]

interface DrillDownLevel {
  title: string
  description?: string
  columns: DrillDownColumn[]
  rows: DrillDownRow[]
  onRowClick?: (row: DrillDownRow) => void
}

const ACTIVE_STATUSES = new Set([
  "discovering", "scoring", "negotiating", "draft", "parsing",
])

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

function HomeSkeleton() {
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
        <Card><CardContent className="pt-6"><Skeleton className="h-[240px]" /></CardContent></Card>
      </main>
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter()
  const { data: session, status } = useSession()

  const [period, setPeriod]         = useState<AnalyticsPeriod>("90d")
  const [analytics, setAnalytics]   = useState<AnalyticsData | null>(null)
  const [loading, setLoading]       = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [drillStack, setDrillStack] = useState<DrillDownLevel[]>([])

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

  if (status === "loading" || (status === "authenticated" && loading)) {
    return <HomeSkeleton />
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

  const kpis = analytics?.kpis
  const cycleReduction = kpis
    ? Math.round(
        ((kpis.baseline_cycle_time_hours - kpis.avg_cycle_time_hours) /
          kpis.baseline_cycle_time_hours) * 100,
      )
    : 0

  // ── Drill-down helpers ────────────────────────────────────────────────────

  function openDrill(level: DrillDownLevel) { setDrillStack([level]) }
  function popDrill()  { setDrillStack((s) => s.slice(0, -1)) }
  function closeDrill() { setDrillStack([]) }

  function navigateToRequest(row: DrillDownRow) {
    const txnId = String(row.request_id ?? "")
    if (!txnId) return
    closeDrill()
    router.push(`/request/${encodeURIComponent(txnId)}/order`)
  }

  function openSpendDrillDown() {
    const total = (analytics?.spend_by_category ?? []).reduce((s, c) => s + c.spend, 0)
    const rows = (analytics?.spend_by_category ?? [])
      .slice()
      .sort((a, b) => b.spend - a.spend)
      .map((c) => ({
        category: c.category,
        spend: c.spend,
        pct: total > 0 ? Math.round((c.spend / total) * 100) : 0,
      })) as unknown as DrillDownRow[]
    openDrill({
      title: "Total Spend — by category",
      description: `Total ${formatINR(total)} across ${rows.length} categories.`,
      columns: COLS_SPEND,
      rows,
    })
  }

  function openSavingsDrillDown() {
    const rows = (analytics?.negotiation_savings ?? [])
      .slice()
      .sort((a, b) => b.total_savings - a.total_savings) as unknown as DrillDownRow[]
    openDrill({
      title: "Total Savings — by category",
      description: "Avg discount and absolute savings from agent negotiation.",
      columns: COLS_NEGOTIATION,
      rows,
    })
  }

  function openCycleDrillDown() {
    const rows = (analytics?.cycle_time_by_category ?? []).map((c) => ({
      category:     c.category,
      before_hours: c.before_hours,
      after_hours:  c.after_hours,
      reduction:    c.before_hours > 0
        ? Math.round(((c.before_hours - c.after_hours) / c.before_hours) * 100)
        : 0,
    })) as unknown as DrillDownRow[]
    openDrill({
      title: "Avg Cycle Time — by category",
      description: "Traditional vs. agent-assisted procurement, by category.",
      columns: COLS_CYCLE,
      rows,
    })
  }

  function openRequestListDrill(title: string, predicate: (r: { status: string; created_at: string }) => boolean, description: string) {
    const rows = (analytics?.recent_requests ?? []).filter(predicate) as unknown as DrillDownRow[]
    openDrill({
      title,
      description,
      columns: COLS_REQUEST_WITH_CAT,
      rows,
      onRowClick: navigateToRequest,
    })
  }

  function openActiveDrillDown() {
    openRequestListDrill(
      "Active Requests",
      (r) => ACTIVE_STATUSES.has(r.status),
      "Click a row to open the order.",
    )
  }

  function openCompletedDrillDown() {
    const monthAgo = new Date()
    monthAgo.setMonth(monthAgo.getMonth() - 1)
    openRequestListDrill(
      "Completed — this month",
      (r) => r.status === "confirmed" && new Date(r.created_at) >= monthAgo,
      "Click a row to open the order.",
    )
  }

  function openPendingDrillDown() {
    openRequestListDrill(
      "Pending Approval",
      (r) => r.status === "pending_approval",
      "Click a row to open the order.",
    )
  }

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8">

        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
          <div>
            <span className="text-xs font-black tracking-[0.2em] uppercase text-primary block mb-1">
              Operations Overview
            </span>
            <h1 className="text-4xl font-extrabold tracking-tight">Home</h1>
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

        {/* KPI Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
          <KpiCard
            title="Total Spend"
            value={kpis ? formatINR(kpis.total_spend) : "—"}
            subtitle={`Period: ${period}`}
            icon={<DollarSign className="h-4 w-4" />}
            onClick={openSpendDrillDown}
          />
          <KpiCard
            title="Total Savings"
            value={kpis ? formatINR(kpis.total_savings) : "—"}
            subtitle={kpis ? `${kpis.savings_percent}% vs market price` : undefined}
            trend={kpis ? { label: `${kpis.savings_percent}% saved`, positive: true } : undefined}
            icon={<TrendingUp className="h-4 w-4" />}
            onClick={openSavingsDrillDown}
          />
          <KpiCard
            title="Active Requests"
            value={kpis ? String(kpis.active_requests) : "—"}
            subtitle="Awaiting response"
            icon={<Clock className="h-4 w-4" />}
            onClick={openActiveDrillDown}
          />
          <KpiCard
            title="Completed"
            value={kpis ? String(kpis.completed_this_month) : "—"}
            subtitle="This month"
            icon={<CheckCircle className="h-4 w-4" />}
            onClick={openCompletedDrillDown}
          />
          <KpiCard
            title="Avg Cycle Time"
            value={kpis ? `${kpis.avg_cycle_time_hours}h` : "—"}
            subtitle={`vs ${kpis?.baseline_cycle_time_hours ?? 72}h traditional`}
            trend={kpis ? { label: `${cycleReduction}% faster`, positive: true } : undefined}
            icon={<BarChart2 className="h-4 w-4" />}
            onClick={openCycleDrillDown}
          />
          <KpiCard
            title="Pend. Approval"
            value={kpis ? String(kpis.pending_approval) : "—"}
            subtitle="Require review"
            icon={<AlertCircle className="h-4 w-4" />}
            onClick={openPendingDrillDown}
          />
        </div>

        {/* Recent Requests */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Recent Requests</CardTitle>
            <CardDescription>
              Most recent purchase requests for the period
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RecentRequestsTable
              requests={analytics?.recent_requests ?? []}
              onRowClick={(req) =>
                router.push(`/request/${encodeURIComponent(req.request_id)}/order`)
              }
            />
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
