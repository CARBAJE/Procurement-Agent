"use client"

import { cn } from "@/lib/utils"

interface CriterionBarProps {
  /** Normalized score in [0, 1] where 1 is best. */
  score: number
  /** Visual hint: a higher score gets a "good" color, lower a "neutral" one. */
  variant?: "good" | "neutral"
  label?: string
  className?: string
}

export default function CriterionBar({
  score,
  variant = "good",
  label,
  className,
}: CriterionBarProps) {
  const clamped = Math.max(0, Math.min(1, score))
  const pct = Math.round(clamped * 100)
  const color =
    variant === "good"
      ? "bg-primary"
      : "bg-muted-foreground/50"

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className="relative h-1.5 flex-1 rounded-full bg-muted overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Score"}
      >
        <div
          className={cn("absolute inset-y-0 left-0 rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">
        {pct}%
      </span>
    </div>
  )
}
