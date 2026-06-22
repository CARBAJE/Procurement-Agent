"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { RefreshCw, Radio, AlertCircle, Wifi, WifiOff } from "lucide-react"
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

type Mode = "ws" | "poll" | "connecting"

/**
 * Status tracker — opens a WebSocket to /ws/status/{txn_id} for live push.
 * Falls back to 30-second polling if the WS can't connect or drops. Keeps
 * the same `onUpdate(StatusSnapshot)` callback so parent components don't
 * need changes.
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
  const [lastUpdateAt, setLastUpdateAt] = useState<Date | null>(null)
  const [ago, setAgo] = useState<string>("never")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>("")
  const [currentState, setCurrentState] = useState<OrderState | null>(initialState)
  const [mode, setMode] = useState<Mode>("connecting")

  // Keep callbacks current so closures don't go stale.
  const onUpdateRef = useRef(onUpdate)
  useEffect(() => { onUpdateRef.current = onUpdate }, [onUpdate])

  const wsRef = useRef<WebSocket | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isTerminal = currentState != null && TERMINAL_STATES.includes(currentState)

  // ── Manual / fallback poll ─────────────────────────────────────────────────
  const pollOnce = useCallback(async () => {
    setBusy(true)
    setError("")
    try {
      const snap = await getOrderStatus(transactionId, orderId, bppId, bppUri)
      setLastUpdateAt(new Date())
      setCurrentState(snap.state)
      onUpdateRef.current(snap)
    } catch (e) {
      setError("Update failed — will retry")
      // eslint-disable-next-line no-console
      console.warn("[StatusPoller] poll error", e)
    } finally {
      setBusy(false)
    }
  }, [transactionId, orderId, bppId, bppUri])

  const startPollingFallback = useCallback(() => {
    if (pollTimerRef.current) return
    setMode("poll")
    // Fire once immediately so the user sees a fresh snapshot.
    pollOnce()
    pollTimerRef.current = setInterval(pollOnce, POLL_MS)
  }, [pollOnce])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  // ── WebSocket lifecycle ────────────────────────────────────────────────────
  useEffect(() => {
    if (isTerminal) return  // Don't open WS for already-finished orders

    // Compute the WS URL based on the current location. In dev the page is
    // served from :3000 but the orchestrator is on :8004.
    const protocol = window.location.protocol === "https:" ? "wss" : "ws"
    // Frontend dev: orchestrator runs on host port 8004. In production the
    // reverse proxy should expose /ws/status under the same origin.
    const host = window.location.hostname
    const orchestratorPort = process.env.NEXT_PUBLIC_ORCHESTRATOR_PORT || "8004"
    const url = `${protocol}://${host}:${orchestratorPort}/ws/status/${encodeURIComponent(transactionId)}`

    let cancelled = false
    setMode("connecting")
    setError("")

    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("[StatusPoller] WS construction failed; using polling", e)
      startPollingFallback()
      return
    }

    wsRef.current = ws

    ws.onopen = () => {
      if (cancelled) return
      setMode("ws")
      // Clear any stale error from a prior connection attempt (e.g. React's
      // Strict Mode double-mount in dev, transient network blips during a
      // reconnect). If we're connected now, by definition there's no error.
      setError("")
      stopPolling()
    }

    ws.onmessage = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as Partial<StatusSnapshot> & { state?: OrderState }
        if (!data.state) return  // Initial snapshot may have null state — ignore
        const snap: StatusSnapshot = {
          transaction_id: data.transaction_id ?? transactionId,
          order_id: data.order_id ?? orderId,
          state: data.state,
          fulfillment_eta: data.fulfillment_eta ?? null,
          tracking_url: data.tracking_url ?? null,
          observed_at: data.observed_at ?? new Date().toISOString(),
          status: data.status ?? "live",
        }
        setLastUpdateAt(new Date())
        setCurrentState(snap.state)
        // Receiving a message is proof the WS is healthy; clear any stale error.
        setError("")
        onUpdateRef.current(snap)
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[StatusPoller] bad WS message", err)
      }
    }

    ws.onerror = () => {
      // Ignore errors on a socket the cleanup has already cancelled — these
      // come from React's Strict Mode double-mount in dev (mount A is closed
      // while mount B is the live one). Without this guard the dead socket's
      // onerror would set a stale "Live connection lost" message on top of a
      // perfectly healthy mount B.
      if (cancelled) return
      // eslint-disable-next-line no-console
      console.warn("[StatusPoller] WS error — falling back to polling")
      setError("Live connection lost — polling instead")
    }

    ws.onclose = () => {
      if (cancelled || isTerminal) return
      // Drop to polling so the user keeps getting updates.
      startPollingFallback()
    }

    return () => {
      cancelled = true
      try { ws.close() } catch { /* noop */ }
      wsRef.current = null
      stopPolling()
    }
  }, [transactionId, orderId, isTerminal, startPollingFallback, stopPolling])

  // Stop polling once the order reaches a terminal state.
  useEffect(() => {
    if (isTerminal) {
      stopPolling()
      try { wsRef.current?.close() } catch { /* noop */ }
    }
  }, [isTerminal, stopPolling])

  // ── "Ns ago" tick ──────────────────────────────────────────────────────────
  useEffect(() => {
    function tick() {
      if (!lastUpdateAt) {
        setAgo("never")
        return
      }
      const secs = Math.floor((Date.now() - lastUpdateAt.getTime()) / 1000)
      if (secs < 5)        setAgo("just now")
      else if (secs < 60)  setAgo(`${secs}s ago`)
      else if (secs < 3600) setAgo(`${Math.floor(secs / 60)}m ago`)
      else                  setAgo(`${Math.floor(secs / 3600)}h ago`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lastUpdateAt])

  return (
    <div className={cn(
      "flex items-center justify-between rounded-lg border bg-card px-4 py-2.5 text-sm",
      className,
    )}>
      <div className="flex items-center gap-2 min-w-0">
        {mode === "ws" ? (
          <Wifi className="h-4 w-4 shrink-0 text-emerald-500" aria-label="Live" />
        ) : mode === "poll" ? (
          <Radio className={cn(
            "h-4 w-4 shrink-0",
            isTerminal ? "text-muted-foreground" :
            busy ? "text-primary animate-pulse" : "text-muted-foreground",
          )} />
        ) : (
          <WifiOff className="h-4 w-4 shrink-0 text-muted-foreground" aria-label="Connecting" />
        )}
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">
            {isTerminal ? (
              <>Tracking stopped — order {currentState?.toLowerCase().replace(/_/g, " ")}</>
            ) : mode === "ws" ? (
              <><span className="text-foreground font-medium">🟢 Live</span> · last update <span className="text-foreground">{ago}</span></>
            ) : mode === "poll" ? (
              <>Polling every {POLL_MS / 1000}s · last update <span className="text-foreground">{ago}</span></>
            ) : (
              <>Connecting…</>
            )}
          </p>
          {error && mode !== "ws" && (
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
        onClick={pollOnce}
        disabled={busy || isTerminal}
        aria-label="Refresh now"
        className="shrink-0"
      >
        <RefreshCw className={cn("h-4 w-4", busy && "animate-spin")} />
      </Button>
    </div>
  )
}
