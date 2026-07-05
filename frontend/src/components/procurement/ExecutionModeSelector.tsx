"use client"

/**
 * ExecutionModeSelector — controls execution_mode for POST /run.
 *
 * This component's ONLY responsibility is surfacing the execution_mode value
 * that ProcurementForm sends to POST /run. It has no knowledge of procurement
 * logic, Beckn, or the orchestrator.
 *
 * Removing this component requires changes only in NewRequestClient.tsx.
 *
 * compact=true: renders as an inline form control (no Card wrapper).
 *               Use when embedding inside an existing card.
 * compact=false (default): renders as a standalone titled Card.
 */

import { cn } from "@/lib/utils"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import type { ExecutionMode } from "@/lib/types"

interface Mode {
  value: ExecutionMode
  label: string
  description: string
}

const MODES: Mode[] = [
  {
    value:       "advisory",
    label:       "Advisory",
    description: "You review all options and make the final selection.",
  },
  {
    value:       "hitl",
    label:       "Human-in-the-Loop",
    description: "Agent recommends one supplier; you approve before commit.",
  },
  {
    value:       "autonomous",
    label:       "Autonomous",
    description: "Agent commits automatically. Large orders escalate for approval.",
  },
]

interface ExecutionModeSelectorProps {
  value: ExecutionMode
  onChange: (mode: ExecutionMode) => void
  compact?: boolean
}

function ModeRadioGroup({
  value,
  onChange,
  compact,
}: ExecutionModeSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Orchestration mode"
      className={cn(
        "grid grid-cols-1 sm:grid-cols-3",
        compact ? "gap-1.5" : "gap-2",
      )}
    >
      {MODES.map((mode) => {
        const selected = value === mode.value
        return (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(mode.value)}
            className={cn(
              "relative text-left transition-all rounded-lg border",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              compact ? "p-2" : "p-3",
              selected
                ? "border-primary bg-primary/5 shadow-sm"
                : "border-border bg-background hover:border-primary/40 hover:bg-secondary/50",
            )}
          >
            {selected && (
              <span
                className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-primary"
                aria-hidden="true"
              />
            )}
            <p className={cn(
              "font-semibold",
              compact ? "text-xs" : "text-sm",
              selected ? "text-primary" : "text-foreground",
            )}>
              {mode.label}
            </p>
            <p className={cn(
              "text-muted-foreground mt-0.5 leading-snug",
              compact ? "text-[10px]" : "text-xs mt-1 leading-relaxed",
            )}>
              {mode.description}
            </p>
          </button>
        )
      })}
    </div>
  )
}

export default function ExecutionModeSelector({
  value,
  onChange,
  compact = false,
}: ExecutionModeSelectorProps) {
  if (compact) {
    return (
      <div className="space-y-1.5">
        <Label className="text-xs">Orchestration mode</Label>
        <ModeRadioGroup value={value} onChange={onChange} compact />
      </div>
    )
  }

  return (
    <Card>
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="h-5 w-1 rounded-full bg-primary shrink-0" aria-hidden="true" />
          <p className="text-sm font-semibold text-foreground">Orchestration Mode</p>
        </div>
        <p className="text-xs text-muted-foreground mb-4">
          Choose how the agent handles this request.
        </p>
        <ModeRadioGroup value={value} onChange={onChange} compact={false} />
      </CardContent>
    </Card>
  )
}
