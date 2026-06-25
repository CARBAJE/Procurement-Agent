"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import {
  CheckCircle,
  XCircle,
  Loader2,
  ClipboardCheck,
  RefreshCw,
  AlertCircle,
} from "lucide-react"
import Navbar from "@/components/layout/Navbar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchPendingApprovals, decideApproval } from "@/lib/api"
import type { PendingApprovalItem } from "@/lib/types"

export default function ApprovalsPage() {
  const router = useRouter()
  const { data: session, status } = useSession()

  const [items, setItems]         = useState<PendingApprovalItem[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [deciding, setDeciding]   = useState<string | null>(null)

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login")
  }, [status, router])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchPendingApprovals())
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(`Could not load pending approvals: ${msg}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (status === "authenticated") load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  async function decide(requestId: string, decision: "approved" | "rejected") {
    setDeciding(requestId)
    try {
      await decideApproval(requestId, decision)
      setItems((prev) => prev.filter((i) => i.request_id !== requestId))
    } catch {
      setError("Failed to record decision. Please try again.")
    } finally {
      setDeciding(null)
    }
  }

  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <>
        <Navbar />
        <main id="main-content" className="container py-8">
          <Skeleton className="h-8 w-48 mb-6" />
          <Skeleton className="h-64 w-full" />
        </main>
      </>
    )
  }

  if (!session) return null

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8 max-w-5xl">
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="h-5 w-1 rounded-full bg-primary shrink-0" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">Pending Review</h2>
            </div>
            <h1 className="text-4xl font-extrabold tracking-tight">Approval Queue</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Orders awaiting your approval
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Refresh
          </Button>
        </div>

        {error && (
          <div role="alert" className="flex items-center gap-2 text-sm text-destructive mb-4">
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
            {error}
          </div>
        )}

        {items.length === 0 && !loading ? (
          <Card>
            <CardContent className="pt-10 pb-10 flex flex-col items-center gap-3">
              <ClipboardCheck className="h-8 w-8 opacity-30" aria-hidden="true" />
              <p role="status" className="text-sm text-muted-foreground">
                No pending approvals at this time.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Pending orders
                <Badge variant="secondary" className="ml-2 text-xs">{items.length}</Badge>
              </CardTitle>
              <CardDescription>
                Review each order and approve or reject it.
              </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requester</TableHead>
                    <TableHead>Item</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>Submitted</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.request_id}>
                      <TableCell className="font-medium">{item.actor.name}</TableCell>
                      <TableCell className="max-w-xs truncate" title={item.item_description}>
                        {item.item_description}
                      </TableCell>
                      <TableCell>{item.provider_name}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        ₹{item.amount_total.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {new Date(item.created_at).toLocaleString("en-US", {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={deciding === item.request_id}
                            onClick={() => decide(item.request_id, "rejected")}
                            aria-label={`Reject order from ${item.actor.name}`}
                          >
                            {deciding === item.request_id ? (
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                            ) : (
                              <XCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
                            )}
                            Reject
                          </Button>
                          <Button
                            size="sm"
                            disabled={deciding === item.request_id}
                            onClick={() => decide(item.request_id, "approved")}
                            aria-label={`Approve order from ${item.actor.name}`}
                          >
                            {deciding === item.request_id ? (
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                            ) : (
                              <CheckCircle className="h-4 w-4" aria-hidden="true" />
                            )}
                            Approve
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </main>
    </>
  )
}
