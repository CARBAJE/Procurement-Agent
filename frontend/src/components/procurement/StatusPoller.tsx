"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { RefreshCw, Radio, AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { getOrderStatus } from "@/lib/api"
import type { OrderState, StatusSnapshot } from "@/lib/types"

const POLL_MS = 30_000
const TERMINAL_STATES: OrderState[] = ["DELIVERED", "CANCELLED"]

interface StatusPollerProps {
  transactionId: string
  orderId: string
  bppId?: string
  bppUri?: string
  initialState: OrderState | null
  onUpdate: (snapshot: StatusSnapshot) => void
  className?: string
}

/**
 * TODO(realtime-ws): replace the setInterval + getOrderStatus call below with
 * a WebSocket subscription to /ws/status/{order_id}. Keep the onUpdate shape
 * (StatusSnapshot) identical so parent components don't need changes.
 * See: Bap-1/docs/ARCHITECTURE.md §7.4 #11.
 */
export default function StatusPoller({
  transactionId,
  orderId,
  bppId,
  bppUri,
  initialState,
  onUpdate,
  className,
}: StatusPollerProps) {
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null)
  const [ago, setAgo] = useState<string>("never")
  const [isPolling, setIsPolling] = useState(false)
  const [error, setError] = useState<string>("")
  const [currentState, setCurrentState] = useState<OrderState | null>(initialState)

  // Keep a ref to the callback so our interval closure doesn't go stale.
  const onUpdateRef = useRef(onUpdate)
  useEffect(() => { onUpdateRef.current = onUpdate }, [onUpdate])

  const isTerminal = currentState != null && TERMINAL_STATES.includes(currentState)

  const poll = useCallback(async () => {
    setIsPolling(true)
    setError("")
    try {
      const snap = await getOrderStatus(transactionId, orderId, bppId, bppUri)
      setLastCheckedAt(new Date())
      setCurrentState(snap.state)
      onUpdateRef.current(snap)
    } catch (e) {
      setError("Poll failed — will retry")
      // eslint-disable-next-line no-console
      console.warn("[StatusPoller] poll error", e)
    } finally {
      setIsPolling(false)
    }
  }, [transactionId, orderId, bppId, bppUri])

  // Kick off polling; stop on terminal state.
  useEffect(() => {
    if (isTerminal) return
    // Run once immediately so the first snapshot lands fast.
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => clearInterval(id)
  }, [poll, isTerminal])

  // Humanized "Ns ago" tick every second.
  useEffect(() => {
    function tick() {
      if (!lastCheckedAt) {
        setAgo("never")
        return
      }
      const secs = Math.floor((Date.now() - lastCheckedAt.getTime()) / 1000)
      if (secs < 5)   setAgo("just now")
      else if (secs < 60)   setAgo(`${secs}s ago`)
      else if (secs < 3600) setAgo(`${Math.floor(secs / 60)}m ago`)
      else                  setAgo(`${Math.floor(secs / 3600)}h ago`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lastCheckedAt])

  return (
    <div className={cn(
      "flex items-center justify-between rounded-lg border bg-card px-4 py-2.5 text-sm",
      className,
    )}>
      <div className="flex items-center gap-2 min-w-0">
        <Radio className={cn(
          "h-4 w-4 shrink-0",
          isTerminal ? "text-muted-foreground" :
          isPolling  ? "text-primary animate-pulse" :
                       "text-muted-foreground",
        )} />
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">
            {isTerminal ? (
              <>Tracking stopped — order {currentState?.toLowerCase().replace(/_/g, " ")}</>
            ) : (
              <>Polling every {POLL_MS / 1000}s · last checked <span className="text-foreground">{ago}</span></>
            )}
          </p>
          {error && (
            <p className="text-xs text-destructive flex items-center gap-1 mt-0.5">
              <AlertCircle className="h-3 w-3" />
              {error}
            </p>
          )}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        onClick={poll}
        disabled={isPolling || isTerminal}
        aria-label="Refresh now"
        className="shrink-0"
      >
        <RefreshCw className={cn("h-4 w-4", isPolling && "animate-spin")} />
      </Button>
    </div>
  )
}
