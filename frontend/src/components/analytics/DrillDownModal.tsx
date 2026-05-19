"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

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
  title: string
  columns: DrillDownColumn[]
  rows: DrillDownRow[]
}

export default function DrillDownModal({
  open,
  onClose,
  title,
  columns,
  rows,
}: DrillDownModalProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Sin registros para este filtro.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  {columns.map((col) => (
                    <th
                      key={col.key}
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
                    className="border-b last:border-0 hover:bg-muted/50 transition-colors"
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
