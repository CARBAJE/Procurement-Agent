// Mirrors Bap-1/src/beckn/models.py and IntentParser/schemas.py
export interface BudgetConstraints {
  max: number
  min?: number
}

export interface BecknIntent {
  item: string
  descriptions: string[]
  quantity: number
  unit: string
  location_coordinates: string  // "lat,lon"
  delivery_timeline: number     // hours (72 = 3 days)
  budget_constraints: BudgetConstraints
}

export type ParsedIntentType = "procurement" | "unknown"

export interface ParseResult {
  intent: ParsedIntentType
  confidence: number
  beckn_intent: BecknIntent | null
  routed_to: string
}

export type UserRole = "requester" | "approver" | "admin"

export interface StubUser {
  id: string
  name: string
  email: string
  role: UserRole
}
