"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2, ArrowRight, ArrowLeft, Search, Send, Package, Star } from "lucide-react"
import { Button }   from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label }    from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge }    from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import IntentPreview from "@/components/procurement/IntentPreview"
import { parseIntent } from "@/lib/api"
import type { ParseResult } from "@/lib/types"

const EXAMPLES = [
  "500 reams papel A4 80gsm blanco, entrega en Bangalore, 3 días, presupuesto máximo ₹200 por resma",
  "200 laptops Dell i7 16GB RAM, campus Mumbai, dentro de 10 días, presupuesto total ₹40 lakh",
  "URGENTE: 50 cilindros oxígeno médico, Hospital Anita Delhi, 6 horas",
]

interface Offering {
  item_id: string
  item_name: string
  provider_name: string
  price_value: string
  price_currency: string
  rating?: string
  fulfillment_hours?: number
  specifications?: string[]
}

interface DiscoverResult {
  transaction_id: string
  offerings: Offering[]
  status: "live" | "mock"
}

type Step = "input" | "preview" | "submitted"

export default function ProcurementForm() {
  const router = useRouter()
  const [query,          setQuery]          = useState("")
  const [step,           setStep]           = useState<Step>("input")
  const [parseResult,    setParseResult]    = useState<ParseResult | null>(null)
  const [discoverResult, setDiscoverResult] = useState<DiscoverResult | null>(null)
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState("")

  async function handleParse(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setError("")
    setLoading(true)
    try {
      const result = await parseIntent(query)
      setParseResult(result)
      setStep("preview")
    } catch {
      setError("No se pudo conectar al IntentParser. Verifica que esté corriendo en :8001.")
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirm() {
    if (!parseResult?.beckn_intent) return
    setError("")
    setLoading(true)
    try {
      const res = await fetch("/api/procurement/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Send the already-parsed BecknIntent — no re-parsing on BAP side
        body: JSON.stringify(parseResult.beckn_intent),
      })
      const data: DiscoverResult = await res.json()
      setDiscoverResult(data)
      setStep("submitted")
    } catch {
      setError("Error al contactar el BAP backend. Verifica que esté corriendo en :8000.")
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setStep("input")
    setQuery("")
    setParseResult(null)
    setDiscoverResult(null)
    setError("")
  }

  if (step === "submitted" && discoverResult) {
    const offerings = discoverResult.offerings ?? []
    return (
      <div className="space-y-4">
        <Card className="border-primary/30">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-primary">
                {offerings.length > 0 ? "Proveedores encontrados" : "Búsqueda iniciada"}
              </CardTitle>
              <Badge variant={discoverResult.status === "live" ? "default" : "secondary"}>
                {discoverResult.status === "live" ? "Red Beckn" : "Catálogo local"}
              </Badge>
            </div>
            <CardDescription className="font-mono text-xs">
              txn: {discoverResult.transaction_id}
            </CardDescription>
          </CardHeader>

          {offerings.length > 0 && (
            <CardContent className="space-y-3">
              {offerings.map((o, i) => (
                <div key={o.item_id ?? i} className="rounded-md border p-3 space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Package className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="font-medium text-sm">{o.provider_name}</span>
                    </div>
                    <span className="font-bold text-sm shrink-0">
                      {o.price_currency} {o.price_value}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground pl-6">{o.item_name}</p>
                  <div className="flex items-center gap-3 pl-6">
                    {o.rating && (
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Star className="h-3 w-3 fill-yellow-400 text-yellow-400" />
                        {o.rating}
                      </span>
                    )}
                    {o.fulfillment_hours && (
                      <span className="text-xs text-muted-foreground">
                        {o.fulfillment_hours}h entrega
                      </span>
                    )}
                  </div>
                </div>
              ))}
              <Separator />
              <p className="text-xs text-muted-foreground">
                Comparación y negociación disponibles en Phase 2.
              </p>
            </CardContent>
          )}

          {offerings.length === 0 && (
            <CardContent>
              <p className="text-sm text-muted-foreground">
                No se encontraron ofertas. Verifica que el Docker stack (ONIX) esté corriendo.
              </p>
            </CardContent>
          )}
        </Card>

        <div className="flex gap-2">
          <Button variant="outline" onClick={() => router.push("/dashboard")}>
            Ir al Dashboard
          </Button>
          <Button onClick={reset}>Nueva Solicitud</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {step === "input" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Search className="h-5 w-5 text-primary" />
              Describe tu necesidad de compra
            </CardTitle>
            <CardDescription>
              Escribe en lenguaje natural qué necesitas comprar.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleParse} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="query">Solicitud</Label>
                <Textarea
                  id="query"
                  placeholder="Ej: 500 reams papel A4 80gsm, entrega en Bangalore, 3 días, presupuesto ₹200/resma"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  rows={4}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" disabled={loading || !query.trim()}>
                {loading
                  ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Analizando…</>
                  : <><ArrowRight className="mr-2 h-4 w-4" />Analizar solicitud</>
                }
              </Button>
            </form>

            <div className="mt-6">
              <p className="text-xs text-muted-foreground mb-2">Ejemplos:</p>
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
              Editar
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={loading || parseResult.intent === "unknown"}
            >
              {loading
                ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Buscando proveedores…</>
                : <><Send className="mr-2 h-4 w-4" />Confirmar y buscar</>
              }
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
