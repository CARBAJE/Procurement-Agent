"use client"

import { useState } from "react"
import {
  Search, BarChart2, CheckCircle, AlertTriangle,
  RefreshCw, FileText, Bell, ShieldCheck, ChevronDown, ChevronRight,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AuditEvent, AuditEventType } from "@/lib/types"

// ── Event type metadata ───────────────────────────────────────────────────────

const EVENT_META: Record<AuditEventType, {
  icon: React.ElementType
  color: string
  bg: string
  label: string
}> = {
  discover:     { icon: Search,      color: "text-blue-600 dark:text-blue-400",   bg: "bg-blue-100 dark:bg-blue-900/40",   label: "Discover"      },
  normalize:    { icon: FileText,    color: "text-slate-600 dark:text-slate-400", bg: "bg-slate-100 dark:bg-slate-800/60", label: "Normalize"     },
  score:        { icon: BarChart2,   color: "text-purple-600 dark:text-purple-400", bg: "bg-purple-100 dark:bg-purple-900/40", label: "Score"     },
  negotiate:    { icon: RefreshCw,   color: "text-yellow-600 dark:text-yellow-400", bg: "bg-yellow-100 dark:bg-yellow-900/40", label: "Negotiate" },
  approve:      { icon: ShieldCheck, color: "text-teal-600 dark:text-teal-400",   bg: "bg-teal-100 dark:bg-teal-900/40",   label: "Approve"       },
  confirm:      { icon: CheckCircle, color: "text-green-600 dark:text-green-400", bg: "bg-green-100 dark:bg-green-900/40", label: "Confirm"       },
  override:     { icon: AlertTriangle, color: "text-orange-500 dark:text-orange-400", bg: "bg-orange-100 dark:bg-orange-900/40", label: "Override" },
  erp_sync:     { icon: RefreshCw,   color: "text-indigo-600 dark:text-indigo-400", bg: "bg-indigo-100 dark:bg-indigo-900/40", label: "ERP Sync"  },
  notification: { icon: Bell,        color: "text-sky-600 dark:text-sky-400",     bg: "bg-sky-100 dark:bg-sky-900/40",     label: "Notification"  },
}

const FALLBACK_META = EVENT_META.normalize

function formatTimestamp(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium", timeStyle: "short",
    })
  } catch {
    return iso
  }
}

// ── Single event row ──────────────────────────────────────────────────────────

function AuditEventRow({ event, isLast }: { event: AuditEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const meta = EVENT_META[event.event_type] ?? FALLBACK_META
  const Icon = meta.icon
  const Chevron = expanded ? ChevronDown : ChevronRight
  const hasPayload = Object.keys(event.reasoning_payload ?? {}).length > 0

  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center" aria-hidden="true">
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${meta.bg}`}>
          <Icon className={`h-4 w-4 ${meta.color}`} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-border my-1" />}
      </div>

      <div className="pb-4 pt-1 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <Badge variant="outline" className="text-xs h-4 px-1.5 py-0">
            {meta.label}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {formatTimestamp(event.event_timestamp)}
          </span>
        </div>

        <p className="text-sm font-medium leading-snug">{event.agent_action}</p>

        {hasPayload && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            aria-expanded={expanded}
          >
            <Chevron className="h-3 w-3" aria-hidden="true" />
            {expanded ? "Hide" : "Show"} reasoning payload
          </button>
        )}

        {expanded && hasPayload && (
          <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed overflow-auto max-h-48 whitespace-pre-wrap break-all">
            {JSON.stringify(event.reasoning_payload, null, 2)}
          </pre>
        )}
      </div>
    </li>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

interface AuditTrailPanelProps {
  events: AuditEvent[]
  title?: string
  className?: string
}

export default function AuditTrailPanel({
  events,
  title = "Audit Trail",
  className,
}: AuditTrailPanelProps) {
  if (events.length === 0) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle className="text-base">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div role="status" className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
            <FileText className="h-8 w-8 opacity-30" aria-hidden="true" />
            <span className="text-sm">No audit events recorded yet.</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          {title}
          <Badge variant="secondary" className="ml-auto text-xs">
            {events.length} event{events.length !== 1 ? "s" : ""}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="relative space-y-0" aria-label="Audit event timeline">
          {events.map((event, i) => (
            <AuditEventRow
              key={event.event_id}
              event={event}
              isLast={i === events.length - 1}
            />
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
