"use client"

import { Loader2, ArrowLeft, AlertTriangle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"

interface ConfirmCancelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onConfirm: () => void
}

export default function ConfirmCancelDialog({
  open,
  onOpenChange,
  submitting,
  onConfirm,
}: ConfirmCancelDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0" aria-hidden="true" />
            Cancel this request?
          </DialogTitle>
          <DialogDescription>
            This discards the current offer comparison and marks the request as
            cancelled in the system. You will be taken back to a new request and
            this selection cannot be recovered.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Keep comparing
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={submitting}
          >
            {submitting ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />Cancelling…</>
            ) : (
              <><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Cancel request</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
