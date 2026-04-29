"use client"

import { Brain, Zap, Eye } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { ReasoningStep } from "@/lib/types"

// ── Role metadata ──────────────────────────────────────────────────────────

const ROLE_META: Record<string, {
  icon: React.ElementType
  color: string
  bg: string
  label: string
}> = {
  reason:  { icon: Brain, color: "text-purple-600 dark:text-purple-400", bg: "bg-purple-100 dark:bg-purple-900/40", label: "Reason"  },
  act:     { icon: Zap,   color: "text-orange-500 dark:text-orange-400", bg: "bg-orange-100 dark:bg-orange-900/40", label: "Act"     },
  observe: { icon: Eye,   color: "text-green-600  dark:text-green-400",  bg: "bg-green-100  dark:bg-green-900/40",  label: "Observe" },
}

// Fallback: parse legacy "[node] text" strings when reasoning_steps is empty.
// Kept for resilience — backend always emits both, but safer to handle nulls.
const NODE_ROLE: Record<string, "reason" | "act" | "observe"> = {
  parse_intent: "reason",
  discover: "act",
  rank_and_select: "reason",
  send_select: "act",
  send_init: "act",
  send_confirm: "act",
  send_status: "act",
  present_results: "observe",
}

function parseLegacyMessage(msg: string): ReasoningStep | null {
  const m = msg.match(/^\[(\w+)\]\s*(.*)$/)
  if (!m) return null
  const node = m[1]
  return {
    node,
    role: NODE_ROLE[node] ?? "observe",
    summary: m[2].trim(),
    timestamp: "",
  }
}

// ── Component ──────────────────────────────────────────────────────────────

interface ReasoningPanelProps {
  steps?: ReasoningStep[]
  messages?: string[]
  title?: string
  className?: string
}

export default function ReasoningPanel({
  steps,
  messages,
  title = "Agent Reasoning",
  className,
}: ReasoningPanelProps) {
  const resolved: ReasoningStep[] =
    steps && steps.length > 0
      ? steps
      : (messages ?? [])
          .map(parseLegacyMessage)
          .filter((s): s is ReasoningStep => s !== null)

  if (resolved.length === 0) return null

  return (
    <Card className={className}>
      <CardHeader className="pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          <Brain className="h-4 w-4 text-muted-foreground" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="relative space-y-0">
          {resolved.map((step, i) => {
            const meta = ROLE_META[step.role] ?? ROLE_META.observe
            const Icon = meta.icon
            const isLast = i === resolved.length - 1
            return (
              <li key={`${step.node}-${i}`} className="flex gap-3">
                <div className="flex flex-col items-center" aria-hidden="true">
                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${meta.bg}`}>
                    <Icon className={`h-4 w-4 ${meta.color}`} />
                  </div>
                  {!isLast && <div className="w-px flex-1 bg-border my-1" />}
                </div>
                <div className="pb-4 pt-1 min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                    <span className={`text-xs font-semibold font-mono ${meta.color}`}>
                      [{step.node}]
                    </span>
                    <Badge variant="outline" className="text-xs h-4 px-1.5 py-0">
                      {meta.label}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground leading-snug">{step.summary}</p>
                </div>
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}
