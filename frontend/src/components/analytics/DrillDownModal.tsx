"use client"

import { ArrowLeft, Inbox } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export interface DrillDownRow {
  [key: string]: string | number | null | undefined
}

export interface DrillDownColumn {
  key: string
  label: string
  render?: (value: string | number | null | undefined, row: DrillDownRow) => React.ReactNode
}

interface DrillDownModalProps {
  open: boolean
  onClose: () => void
  onBack?: () => void
  title: string
  description?: string
  columns: DrillDownColumn[]
  rows: DrillDownRow[]
  onRowClick?: (row: DrillDownRow) => void
}

export default function DrillDownModal({
  open,
  onClose,
  onBack,
  title,
  description,
  columns,
  rows,
  onRowClick,
}: DrillDownModalProps) {
  const interactive = Boolean(onRowClick)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            {onBack && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onBack}
                aria-label="Back to previous level"
                className="h-7 w-7 p-0 shrink-0"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              </Button>
            )}
            <DialogTitle>{title}</DialogTitle>
          </div>
          {description && (
            <DialogDescription>{description}</DialogDescription>
          )}
        </DialogHeader>

        {rows.length === 0 ? (
          <div role="status" className="flex flex-col items-center gap-2 py-10 text-center">
            <Inbox className="h-8 w-8 opacity-30" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">
              No records match this filter.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      scope="col"
                      className="text-left py-2 px-3 font-medium text-muted-foreground"
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={i}
                    onClick={interactive ? () => onRowClick!(row) : undefined}
                    onKeyDown={
                      interactive
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              onRowClick!(row)
                            }
                          }
                        : undefined
                    }
                    tabIndex={interactive ? 0 : undefined}
                    role={interactive ? "button" : undefined}
                    className={cn(
                      "border-b last:border-0 transition-colors",
                      interactive
                        ? "cursor-pointer hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                        : "hover:bg-muted/50",
                    )}
                  >
                    {columns.map((col) => (
                      <td key={col.key} className="py-2 px-3">
                        {col.render
                          ? col.render(row[col.key], row)
                          : String(row[col.key] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
