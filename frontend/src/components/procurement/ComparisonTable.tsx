"use client"

import React, { useMemo, useState } from "react"
import {
  ArrowDown, ArrowUp, ArrowUpDown,
  Trophy, Star, Package,
  CheckCircle2, ChevronDown, ChevronRight,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { Offering } from "@/lib/types"

// ── Sort ────────────────────────────────────────────────────────────────────

type SortKey = "provider_name" | "price_value" | "rating" | "available_quantity" | "fulfillment_hours"
type SortDir = "asc" | "desc"

function compare(a: Offering, b: Offering, key: SortKey, dir: SortDir): number {
  const av = getSortable(a, key)
  const bv = getSortable(b, key)
  // Null/undefined sorted to the bottom regardless of direction.
  if (av === null && bv === null) return 0
  if (av === null) return 1
  if (bv === null) return -1
  let n: number
  if (typeof av === "string" && typeof bv === "string") {
    n = av.localeCompare(bv)
  } else {
    n = (av as number) - (bv as number)
  }
  return dir === "asc" ? n : -n
}

function getSortable(o: Offering, key: SortKey): string | number | null {
  switch (key) {
    case "provider_name":      return o.provider_name
    case "price_value":        return parseFloat(o.price_value)
    case "rating":             return o.rating ? parseFloat(o.rating) : null
    case "available_quantity": return o.available_quantity ?? null
    case "fulfillment_hours":  return o.fulfillment_hours ?? null
  }
}

function formatStock(q?: number | null): string {
  if (q == null) return "—"
  if (q >= 1000) return `${(q / 1000).toFixed(q % 1000 === 0 ? 0 : 1)}k`
  return q.toString()
}

function formatDelivery(h?: number | null): string {
  if (h == null) return "—"
  if (h < 24) return `${h}h`
  return `${Math.round(h / 24)}d`
}

// ── Header cell ─────────────────────────────────────────────────────────────

interface HeaderProps {
  label: string
  sortKey?: SortKey
  currentKey?: SortKey
  currentDir?: SortDir
  onSort?: (key: SortKey) => void
  className?: string
}

function SortableHeader({ label, sortKey, currentKey, currentDir, onSort, className }: HeaderProps) {
  if (!sortKey || !onSort) return <TableHead className={className}>{label}</TableHead>
  const active = currentKey === sortKey
  const Icon = !active ? ArrowUpDown : currentDir === "asc" ? ArrowUp : ArrowDown
  const ariaSort = !active ? "none" : currentDir === "asc" ? "ascending" : "descending"
  return (
    <TableHead className={className} aria-sort={ariaSort as "ascending" | "descending" | "none"}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 font-medium text-muted-foreground text-xs uppercase tracking-wide hover:text-foreground transition-colors"
      >
        {label}
        <Icon className={cn("h-3 w-3", active ? "text-foreground" : "opacity-60")} />
      </button>
    </TableHead>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

interface ComparisonTableProps {
  offerings: Offering[]
  recommendedItemId: string | null
  selectedItemId: string | null
  onSelect: (itemId: string) => void
  disabledProceed?: boolean
}

export default function ComparisonTable({
  offerings,
  recommendedItemId,
  selectedItemId,
  onSelect,
}: ComparisonTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("price_value")
  const [sortDir, setSortDir] = useState<SortDir>("asc")
  const [openSpecs, setOpenSpecs] = useState<Set<string>>(new Set())

  const sorted = useMemo(
    () => [...offerings].sort((a, b) => compare(a, b, sortKey, sortDir)),
    [offerings, sortKey, sortDir],
  )

  function onSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      // Numeric columns default to ascending for price, descending for rating/stock.
      setSortDir(key === "rating" || key === "available_quantity" ? "desc" : "asc")
    }
  }

  function toggleSpecs(itemId: string) {
    setOpenSpecs((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  // Keyboard nav: arrows move focus between rows; Enter selects.
  function onRowKeyDown(e: React.KeyboardEvent<HTMLTableRowElement>, itemId: string, idx: number) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      onSelect(itemId)
      return
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault()
      const delta = e.key === "ArrowDown" ? 1 : -1
      const next = Math.max(0, Math.min(sorted.length - 1, idx + delta))
      const target = document.querySelector<HTMLTableRowElement>(
        `tr[data-row-index="${next}"]`,
      )
      target?.focus()
    }
  }

  if (!offerings.length) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
        <Package className="h-8 w-8 opacity-30 mb-2" aria-hidden="true" />
        <span className="text-sm">No offerings found for this request.</span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-card">
      {/* table-fixed + per-column widths keep everything inside the card — no
          horizontal scroll. Long provider/item text truncates with a title tooltip. */}
      <Table className="table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[5%]" aria-hidden="true" />
            <SortableHeader label="Provider" sortKey="provider_name" currentKey={sortKey} currentDir={sortDir} onSort={onSort} className="w-[28%]" />
            <SortableHeader label="Price"    sortKey="price_value"   currentKey={sortKey} currentDir={sortDir} onSort={onSort} className="w-[13%] text-right" />
            <SortableHeader label="Rating"   sortKey="rating"        currentKey={sortKey} currentDir={sortDir} onSort={onSort} className="w-[11%]" />
            <SortableHeader label="Stock"    sortKey="available_quantity" currentKey={sortKey} currentDir={sortDir} onSort={onSort} className="w-[10%]" />
            <SortableHeader label="Delivery" sortKey="fulfillment_hours"  currentKey={sortKey} currentDir={sortDir} onSort={onSort} className="w-[11%]" />
            <TableHead className="w-[12%]">Specs</TableHead>
            <TableHead className="w-[10%] text-right">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((o, idx) => {
            const isRecommended = o.item_id === recommendedItemId
            const isSelected    = o.item_id === selectedItemId
            const specsOpen     = openSpecs.has(o.item_id)
            const specs         = o.specifications ?? []

            return (
              <React.Fragment key={o.item_id}>
                <TableRow
                  data-row-index={idx}
                  tabIndex={0}
                  onKeyDown={(e) => onRowKeyDown(e, o.item_id, idx)}
                  onClick={() => onSelect(o.item_id)}
                  className={cn(
                    "cursor-pointer focus:outline-none",
                    isSelected && "bg-primary/5 hover:bg-primary/10",
                    isRecommended && !isSelected && "bg-primary/[0.03]",
                    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                  )}
                  aria-label={`${o.provider_name} at ${o.price_currency} ${o.price_value}${isRecommended ? " — recommended by the agent" : ""}`}
                  aria-selected={isSelected}
                >
                  <TableCell className="px-3">
                    {isSelected ? (
                      <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />
                    ) : isRecommended ? (
                      <Trophy className="h-4 w-4 text-primary/70" aria-hidden="true" />
                    ) : (
                      <Package className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={cn("font-semibold text-sm truncate", isRecommended && "text-primary")}
                        title={o.provider_name}
                      >
                        {o.provider_name}
                      </span>
                      {isRecommended && (
                        <Badge className="text-[10px] h-4 px-1.5 py-0 shrink-0">Recommended</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground truncate" title={o.item_name}>{o.item_name}</p>
                  </TableCell>
                  <TableCell className="text-right font-bold tabular-nums whitespace-nowrap">
                    {o.price_currency} {o.price_value}
                  </TableCell>
                  <TableCell>
                    {o.rating ? (
                      <span className="inline-flex items-center gap-1 text-sm">
                        <Star className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
                        {o.rating}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="text-sm tabular-nums">{formatStock(o.available_quantity)}</span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm tabular-nums">{formatDelivery(o.fulfillment_hours)}</span>
                  </TableCell>
                  <TableCell>
                    {specs.length > 0 ? (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); toggleSpecs(o.item_id) }}
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        aria-expanded={specsOpen}
                        aria-controls={`specs-${o.item_id}`}
                      >
                        {specsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                        {specs.length}
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant={isSelected ? "default" : "outline"}
                      onClick={(e) => { e.stopPropagation(); onSelect(o.item_id) }}
                    >
                      {isSelected ? "Selected" : "Select"}
                    </Button>
                  </TableCell>
                </TableRow>
                {specsOpen && specs.length > 0 && (
                  <TableRow key={`${o.item_id}-specs`} className="bg-muted/30 hover:bg-muted/30">
                    <TableCell />
                    <TableCell colSpan={7} id={`specs-${o.item_id}`}>
                      <div className="flex flex-wrap gap-1.5 py-1">
                        {specs.map((s) => (
                          <Badge key={s} variant="outline" className="text-xs font-normal">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
