"use client"

import { Trophy, Sparkles } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import CriterionBar from "@/components/procurement/CriterionBar"
import type { Offering, Scoring, ScoringRanking, ScoringRow } from "@/lib/types"

function criterionDisplayName(key: string): string {
  if (key === "ml_score") return "ML Score"
  if (key === "price") return "Price"
  return key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())
}

function criterionExplanation(
  key: string,
  row: ScoringRow,
  ranking: ScoringRanking[],
  totalOffers: number,
): string {
  if (key !== "ml_score") return row.explanation
  const rank = ranking.find((r) => r.item_id === row.item_id)?.rank
  if (!rank) return row.explanation
  return rank === 1 ? "Top-ranked offer" : `Ranked #${rank} of ${totalOffers}`
}

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
                  <span className="text-sm font-medium">{criterionDisplayName(c.key)}</span>
                  <span className="text-xs text-muted-foreground">
                    Weight {Math.round(c.weight * 100)}%
                  </span>
                </div>
                <CriterionBar score={row.normalized} label={criterionDisplayName(c.key)} />
                <p className="text-xs text-muted-foreground mt-1">
                  {criterionExplanation(c.key, row, scoring.ranking, offerings.length)}
                </p>
              </div>
            )
          })}
        </div>

      </CardContent>
    </Card>
  )
}
