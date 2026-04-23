"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Package, Star, Trophy, CheckCircle2,
  Brain, Zap, Eye, ShoppingCart, Hash,
} from "lucide-react"
import type { DiscoverResult, Offering } from "@/lib/types"

// ── Node metadata ──────────────────────────────────────────────────────────────

const NODE_META: Record<string, {
  icon: React.ElementType
  color: string
  bg: string
  role: string
}> = {
  "[intention-parser]":        { icon: Brain, color: "text-purple-600 dark:text-purple-400", bg: "bg-purple-100 dark:bg-purple-900/40", role: "Reason"  },
  "[beckn-bap-client]":        { icon: Zap,   color: "text-orange-500 dark:text-orange-400", bg: "bg-orange-100 dark:bg-orange-900/40", role: "Act"     },
  "[comparative-scoring]":     { icon: Brain, color: "text-purple-600 dark:text-purple-400", bg: "bg-purple-100 dark:bg-purple-900/40", role: "Reason"  },
  "[beckn-bap-client/select]": { icon: Zap,   color: "text-orange-500 dark:text-orange-400", bg: "bg-orange-100 dark:bg-orange-900/40", role: "Act"     },
  "[orchestrator]":            { icon: Eye,   color: "text-green-600  dark:text-green-400",  bg: "bg-green-100  dark:bg-green-900/40",  role: "Observe" },
}

function getNodeMeta(msg: string) {
  for (const [tag, meta] of Object.entries(NODE_META)) {
    if (msg.startsWith(tag)) {
      return { ...meta, tag, content: msg.replace(tag, "").trim() }
    }
  }
  return null
}

function extractAck(messages: string[]): string {
  const line = messages.find(m => m.startsWith("[beckn-bap-client/select]"))
  if (!line) return "—"
  return line.match(/ACK=(\w+)/)?.[1] ?? "—"
}

function extractSummary(messages: string[]): string {
  const line = messages.find(m => m.startsWith("[orchestrator]"))
  return line ? line.replace("[orchestrator] ", "") : ""
}

// ── Offering row ──────────────────────────────────────────────────────────────

function OfferingRow({ offering, isSelected }: { offering: Offering; isSelected: boolean }) {
  return (
    <div className={`flex items-center justify-between rounded-lg border px-4 py-3 transition-colors ${
      isSelected
        ? "border-primary bg-primary/5 shadow-sm"
        : "border-border bg-card hover:bg-muted/40"
    }`}>
      <div className="flex items-center gap-3 min-w-0">
        {isSelected
          ? <Trophy className="h-4 w-4 text-primary shrink-0" />
          : <Package className="h-4 w-4 text-muted-foreground shrink-0" />
        }
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`font-semibold text-sm ${isSelected ? "text-primary" : ""}`}>
              {offering.provider_name}
            </span>
            {isSelected && (
              <Badge className="text-xs h-5">Selected</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate">{offering.item_name}</p>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0 ml-3">
        {offering.rating && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Star className="h-3 w-3 fill-yellow-400 text-yellow-400" />
            {offering.rating}
          </span>
        )}
        <span className={`font-bold text-sm tabular-nums ${isSelected ? "text-primary" : ""}`}>
          {offering.price_currency} {offering.price_value}
        </span>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function AgentResults({ result }: { result: DiscoverResult }) {
  const { offerings, selected, messages, transaction_id, status } = result
  const ackStatus = extractAck(messages)
  const summary   = extractSummary(messages)

  return (
    <div className="space-y-6">

      {/* ── Top header bar ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-xl font-bold">Procurement Results</h2>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Hash className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-mono">{transaction_id}</span>
          </div>
        </div>
        <Badge variant={status === "live" ? "default" : "secondary"} className="text-sm px-3 py-1">
          {status === "live" ? "Live Beckn Network" : "Local Catalog"}
        </Badge>
      </div>

      {/* ── Two-column grid: offerings + selection ─────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Left — discover: all offerings */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Package className="h-4 w-4 text-muted-foreground" />
              {offerings.length > 0
                ? `${offerings.length} Providers Found`
                : "No Providers Found"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {offerings.length > 0
              ? offerings.map((o, i) => (
                  <OfferingRow
                    key={o.item_id ?? i}
                    offering={o}
                    isSelected={selected?.provider_id === o.provider_id}
                  />
                ))
              : <p className="text-sm text-muted-foreground">
                  No offerings returned. Verify the Docker stack (ONIX) is running.
                </p>
            }
          </CardContent>
        </Card>

        {/* Right — rank_and_select + send_select */}
        <div className="space-y-4">

          {/* rank_and_select — selected provider detail */}
          {selected ? (
            <Card className="border-primary/40">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Trophy className="h-4 w-4 text-primary" />
                  Selected Provider
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <p className="text-2xl font-bold text-primary">{selected.provider_name}</p>
                  <p className="text-sm text-muted-foreground">{selected.item_name}</p>
                </div>
                <Separator />
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Unit Price</p>
                    <p className="font-bold text-lg">{selected.price_currency} {selected.price_value}</p>
                  </div>
                  {selected.rating && (
                    <div>
                      <p className="text-xs text-muted-foreground uppercase tracking-wide">Rating</p>
                      <p className="font-semibold flex items-center gap-1">
                        <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />
                        {selected.rating}
                      </p>
                    </div>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  Cheapest of {offerings.length} — Phase 1 ranking criterion
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-6 text-center text-sm text-muted-foreground">
                No provider selected
              </CardContent>
            </Card>
          )}

          {/* send_select — /select ACK */}
          {selected && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ShoppingCart className="h-4 w-4 text-muted-foreground" />
                  Purchase Signal Sent
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center justify-between">
                <div className="text-sm">
                  <code className="text-xs bg-muted px-1 py-0.5 rounded">/select</code>
                  {" → "}
                  <span className="font-medium">{selected.provider_name}</span>
                </div>
                <Badge variant={ackStatus === "ACK" ? "default" : "destructive"}>
                  {ackStatus}
                </Badge>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ── present_results — order summary ────────────────────────────────── */}
      {summary && (
        <Card className="border-green-500/40 bg-gradient-to-r from-green-50/60 to-emerald-50/40 dark:from-green-950/30 dark:to-emerald-950/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2 text-green-700 dark:text-green-400">
              <CheckCircle2 className="h-5 w-5" />
              Order Summary
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed">{summary}</p>
          </CardContent>
        </Card>
      )}

      {/* ── Agent reasoning trace — timeline ───────────────────────────────── */}
      {messages.length > 0 && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="h-4 w-4 text-muted-foreground" />
              Agent Reasoning
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative space-y-0">
              {messages.map((msg, i) => {
                const meta = getNodeMeta(msg)
                if (!meta) return null
                const Icon = meta.icon
                const isLast = i === messages.length - 1
                return (
                  <div key={i} className="flex gap-3">
                    {/* timeline line */}
                    <div className="flex flex-col items-center">
                      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${meta.bg}`}>
                        <Icon className={`h-4 w-4 ${meta.color}`} />
                      </div>
                      {!isLast && <div className="w-px flex-1 bg-border my-1" />}
                    </div>
                    {/* content */}
                    <div className={`pb-4 pt-1 min-w-0 flex-1 ${isLast ? "" : ""}`}>
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`text-xs font-semibold font-mono ${meta.color}`}>
                          {meta.tag}
                        </span>
                        <Badge variant="outline" className="text-xs h-4 px-1.5 py-0">
                          {meta.role}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground leading-snug">{meta.content}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
