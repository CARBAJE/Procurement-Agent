"use client"

import { Trophy, Sparkles } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import CriterionBar from "@/components/procurement/CriterionBar"
import type { Offering, Scoring } from "@/lib/types"

interface ScoringPanelProps {
  scoring: Scoring
  offerings: Offering[]
  selectedItemId?: string | null
}

export default function ScoringPanel({
  scoring,
  offerings,
  selectedItemId,
}: ScoringPanelProps) {
  const focusItemId = selectedItemId ?? scoring.recommended_item_id
  const offering = offerings.find((o) => o.item_id === focusItemId)

  if (!offering) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            Agent Scoring
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Pick an offering to see its score breakdown.</p>
        </CardContent>
      </Card>
    )
  }

  const isRecommended = offering.item_id === scoring.recommended_item_id

  return (
    <Card className={isRecommended ? "border-primary/40" : undefined}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          {isRecommended ? (
            <Trophy className="h-4 w-4 text-primary" />
          ) : (
            <Sparkles className="h-4 w-4 text-muted-foreground" />
          )}
          {isRecommended ? "Why this is recommended" : "Your selection"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-lg font-bold leading-tight">{offering.provider_name}</p>
          <p className="text-sm text-muted-foreground">{offering.item_name}</p>
          <p className="mt-1 text-2xl font-bold text-primary tabular-nums">
            {offering.price_currency} {offering.price_value}
          </p>
        </div>

        <Separator />

        <div className="space-y-3">
          {scoring.criteria.map((c) => {
            const row = c.scores.find((s) => s.item_id === offering.item_id)
            if (!row) return null
            return (
              <div key={c.key}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium">{c.label}</span>
                  <span className="text-xs text-muted-foreground">
                    Weight {Math.round(c.weight * 100)}%
                  </span>
                </div>
                <CriterionBar score={row.normalized} label={c.label} />
                <p className="text-xs text-muted-foreground mt-1">{row.explanation}</p>
              </div>
            )
          })}
        </div>

        {/* Forward-compat note: today only "price" is scored. The future
            Comparison Engine will inject TCO, reputation, delivery reliability
            and compliance criteria — this panel renders whatever arrives. */}
        {scoring.criteria.length === 1 && (
          <p className="text-xs text-muted-foreground italic">
            More criteria (delivery reliability, reputation, compliance) will be
            added by the scoring engine.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
