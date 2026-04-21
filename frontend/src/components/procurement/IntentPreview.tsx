import type { ParseResult } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { CheckCircle2, Package, MapPin, Clock, Wallet, Tag } from "lucide-react"

function hoursToLabel(h: number): string {
  if (h < 24) return `${h}h`
  const days = Math.round(h / 24)
  return `${days} day${days !== 1 ? "s" : ""}`
}

function confidenceColor(c: number): "default" | "secondary" | "destructive" {
  if (c >= 0.85) return "default"
  if (c >= 0.60) return "secondary"
  return "destructive"
}

interface IntentPreviewProps {
  result: ParseResult
  originalQuery: string
}

export default function IntentPreview({ result, originalQuery }: IntentPreviewProps) {
  const intent = result.beckn_intent

  if (!intent || result.intent === "unknown") {
    return (
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive text-base">Could not interpret the request</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Try being more specific. Example: &ldquo;500 reams A4 paper 80gsm, Bangalore, 3 days, budget ₹200/ream&rdquo;
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Request interpreted</CardTitle>
          </div>
          <Badge variant={confidenceColor(result.confidence)}>
            {Math.round(result.confidence * 100)}% confidence
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground italic">&ldquo;{originalQuery}&rdquo;</p>
      </CardHeader>

      <Separator />

      <CardContent className="pt-4 grid gap-3">
        <div className="flex items-start gap-3">
          <Package className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">Item</p>
            <p className="font-medium">{intent.item}</p>
            {intent.descriptions.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {intent.descriptions.map((d, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">{d}</Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Tag className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">Quantity</p>
            <p className="font-medium">{intent.quantity} {intent.unit}</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Clock className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">Delivery timeline</p>
            <p className="font-medium">{hoursToLabel(intent.delivery_timeline)}</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Wallet className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">Max budget</p>
            <p className="font-medium">₹{intent.budget_constraints.max.toLocaleString()}</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <MapPin className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">Delivery coordinates</p>
            <p className="font-medium text-sm font-mono">{intent.location_coordinates}</p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground pt-1">
          Model: <span className="font-mono">{result.routed_to}</span>
        </p>
      </CardContent>
    </Card>
  )
}
