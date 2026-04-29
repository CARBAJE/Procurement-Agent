"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import axios from "axios"
import { Loader2, ArrowRight, ArrowLeft, Search, Send } from "lucide-react"
import { Button }   from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label }    from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import IntentPreview from "@/components/procurement/IntentPreview"
import { compareOfferings, parseIntent } from "@/lib/api"
import { saveSession } from "@/lib/session-store"
import type { ParseResult } from "@/lib/types"

function extractServerError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && err.response?.data) {
    const data = err.response.data as { error?: string; detail?: string }
    if (data.detail) return `${data.error ?? "Server error"}: ${data.detail}`
    if (data.error)  return data.error
  }
  return fallback
}

const EXAMPLES = [
  "500 reams A4 paper 80gsm white, delivery in Bangalore, 3 days, max budget ₹200 per ream",
  "200 Dell laptops i7 16GB RAM, Mumbai campus, within 10 days, total budget ₹40 lakh",
  "URGENT: 50 medical oxygen cylinders, Anita Hospital Delhi, 6 hours",
]

type Step = "input" | "preview"

export default function ProcurementForm() {
  const router = useRouter()
  const [query,       setQuery]       = useState("")
  const [step,        setStep]        = useState<Step>("input")
  const [parseResult, setParseResult] = useState<ParseResult | null>(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState("")

  async function handleParse(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setError("")
    setLoading(true)
    try {
      const result = await parseIntent(query)
      setParseResult(result)
      setStep("preview")
    } catch (err) {
      setError(extractServerError(
        err,
        "Could not connect to the server. Make sure the backend services are running (ports 8001 and 8004).",
      ))
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirm() {
    if (!parseResult?.beckn_intent) return
    setError("")
    setLoading(true)
    try {
      const comparison = await compareOfferings(parseResult.beckn_intent)
      // Persist intent + comparison under the transaction id. CompareView
      // will overwrite with the user's pick and the commit result.
      saveSession(comparison.transaction_id, {
        intent: parseResult.beckn_intent,
        comparison,
        chosenItemId: comparison.recommended_item_id,
        commit: null,
      })
      router.push(`/request/${encodeURIComponent(comparison.transaction_id)}/compare`)
    } catch (err) {
      setError(extractServerError(
        err,
        "Error contacting the BAP backend. Make sure it is running on :8000.",
      ))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div className="mb-2">
        <h1 className="text-3xl font-bold">New Request</h1>
        <p className="text-muted-foreground">Describe in natural language what you need to purchase</p>
      </div>

      {step === "input" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Search className="h-5 w-5 text-primary" />
              Describe your purchase need
            </CardTitle>
            <CardDescription>
              Write in natural language what you need to buy.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleParse} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="query">Request</Label>
                <Textarea
                  id="query"
                  placeholder="E.g.: 500 reams A4 paper 80gsm, delivery in Bangalore, 3 days, budget ₹200/ream"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  rows={4}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" disabled={loading || !query.trim()}>
                {loading
                  ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Analyzing…</>
                  : <><ArrowRight className="mr-2 h-4 w-4" />Analyze request</>
                }
              </Button>
            </form>

            <div className="mt-6">
              <p className="text-xs text-muted-foreground mb-2">Examples:</p>
              <div className="space-y-2">
                {EXAMPLES.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setQuery(ex)}
                    className="w-full text-left text-xs p-2 rounded border border-dashed border-muted-foreground/30 text-muted-foreground hover:border-primary/50 hover:text-foreground transition-colors"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "preview" && parseResult && (
        <div className="space-y-4">
          <IntentPreview result={parseResult} originalQuery={query} />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => setStep("input")} disabled={loading}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Edit
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={loading || parseResult.intent === "unknown"}
            >
              {loading
                ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Searching providers…</>
                : <><Send className="mr-2 h-4 w-4" />Compare offers</>
              }
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
