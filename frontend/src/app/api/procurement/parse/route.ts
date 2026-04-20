import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const query: string = body?.query
  if (!query?.trim()) {
    return NextResponse.json({ error: "query is required" }, { status: 400 })
  }

  const intentParserUrl = process.env.INTENT_PARSER_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.post(`${intentParserUrl}/parse`, { query })
    return NextResponse.json(data)
  } catch (err) {
    console.error("[parse proxy] IntentParser error:", err)
    return NextResponse.json({
      intent: "procurement",
      confidence: 0.95,
      beckn_intent: {
        item: query,
        descriptions: [],
        quantity: 1,
        unit: "unit",
        location_coordinates: "12.9716,77.5946",
        delivery_timeline: 72,
        budget_constraints: { max: 1000 },
      },
      routed_to: "mock (IntentParser offline)",
    })
  }
}
