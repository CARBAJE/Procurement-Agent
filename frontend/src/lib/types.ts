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

export interface Offering {
  bpp_id: string
  bpp_uri?: string
  provider_id: string
  provider_name: string
  item_id: string
  item_name: string
  price_value: string
  price_currency: string
  rating?: string
  fulfillment_hours?: number
  specifications?: string[]
}

export interface DiscoverResult {
  transaction_id: string
  offerings: Offering[]
  selected: Offering | null
  messages: string[]
  status: "live" | "mock"
}

export type UserRole = "requester" | "approver" | "admin"

export interface StubUser {
  id: string
  name: string
  email: string
  role: UserRole
}
