"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import { Save, RefreshCw, AlertCircle, Users } from "lucide-react"
import Navbar from "@/components/layout/Navbar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
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
import { fetchAdminUsers, updateAdminUser } from "@/lib/api"
import type { AdminUser } from "@/lib/types"

const ROLE_COLORS: Record<string, "default" | "secondary" | "outline"> = {
  requester: "secondary",
  approver:  "default",
  admin:     "outline",
}

type RowEdit = { approval_threshold: string }

export default function AdminPage() {
  const router = useRouter()
  const { data: session, status } = useSession()

  const [users, setUsers]         = useState<AdminUser[]>([])
  const [edits, setEdits]         = useState<Record<string, RowEdit>>({})
  const [saving, setSaving]       = useState<string | null>(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [saveError, setSaveError] = useState<Record<string, string>>({})

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login")
  }, [status, router])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAdminUsers()
      setUsers(data)
      // Initialise edit state from server values.
      const initial: Record<string, RowEdit> = {}
      data.forEach((u) => {
        initial[u.user_id] = {
          approval_threshold: String(u.approval_threshold),
        }
      })
      setEdits(initial)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(`Could not load users: ${msg}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (status === "authenticated") load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  async function save(userId: string) {
    const edit = edits[userId]
    if (!edit) return
    const threshold = parseFloat(edit.approval_threshold)
    if (isNaN(threshold) || threshold < 0) {
      setSaveError((prev) => ({ ...prev, [userId]: "Threshold must be a non-negative number." }))
      return
    }
    setSaving(userId)
    setSaveError((prev) => { const next = { ...prev }; delete next[userId]; return next })
    try {
      const updated = await updateAdminUser(userId, {
        approval_threshold: threshold,
      })
      setUsers((prev) => prev.map((u) => (u.user_id === userId ? updated : u)))
      setEdits((prev) => ({
        ...prev,
        [userId]: {
          approval_threshold: String(updated.approval_threshold),
        },
      }))
    } catch {
      setSaveError((prev) => ({ ...prev, [userId]: "Failed to save. Please try again." }))
    } finally {
      setSaving(null)
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
              <h2 className="text-sm font-semibold text-foreground">User Management</h2>
            </div>
            <h1 className="text-4xl font-extrabold tracking-tight">Admin Panel</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Edit roles and approval thresholds
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

        {users.length === 0 && !loading ? (
          <Card>
            <CardContent className="pt-10 pb-10 flex flex-col items-center gap-3">
              <Users className="h-8 w-8 opacity-30" aria-hidden="true" />
              <p role="status" className="text-sm text-muted-foreground">
                No users found. Run the seed script or log in for the first time.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                All users
                <Badge variant="secondary" className="ml-2 text-xs">{users.length}</Badge>
              </CardTitle>
              <CardDescription>
                Changes take effect immediately. Threshold is the max auto-approval amount in ₹.
              </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Department</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Threshold (₹)</TableHead>
                    <TableHead className="text-right">Save</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => {
                    const edit  = edits[user.user_id]
                    const err   = saveError[user.user_id]
                    const busy  = saving === user.user_id
                    return (
                      <TableRow key={user.user_id}>
                        <TableCell className="font-medium">{user.name}</TableCell>
                        <TableCell className="text-muted-foreground text-sm">{user.email}</TableCell>
                        <TableCell className="text-sm">{user.department}</TableCell>
                        <TableCell>
                          <Badge variant={ROLE_COLORS[user.role] ?? "secondary"} className="text-xs" title="Managed in Keycloak">
                            {user.role}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {edit ? (
                            <div className="space-y-1">
                              <Input
                                type="number"
                                min={0}
                                step={1000}
                                value={edit.approval_threshold}
                                onChange={(e) =>
                                  setEdits((prev) => ({
                                    ...prev,
                                    [user.user_id]: {
                                      ...prev[user.user_id],
                                      approval_threshold: e.target.value,
                                    },
                                  }))
                                }
                                className="h-8 w-[140px] tabular-nums"
                                aria-label={`Approval threshold for ${user.name}`}
                              />
                              {err && (
                                <p role="alert" className="text-xs text-destructive">{err}</p>
                              )}
                            </div>
                          ) : (
                            <span className="tabular-nums text-sm">
                              ₹{user.approval_threshold.toLocaleString("en-IN")}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() => save(user.user_id)}
                            aria-label={`Save changes for ${user.name}`}
                          >
                            {busy ? (
                              <><RefreshCw className="mr-2 h-3 w-3 animate-spin" aria-hidden="true" />Saving…</>
                            ) : (
                              <><Save className="mr-2 h-3 w-3" aria-hidden="true" />Save</>
                            )}
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </main>
    </>
  )
}
