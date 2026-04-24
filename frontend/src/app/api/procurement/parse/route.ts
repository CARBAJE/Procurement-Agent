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
    // Surface the upstream failure verbatim — no silent mock fallback. The
    // UI must show the user that NLP parsing failed rather than proceed
    // with a fabricated intent (e.g., quantity=1, default coords) that
    // doesn't reflect the query.
    console.error("[parse proxy] IntentParser error:", err)
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(
        err.response.data ?? { error: "Intent parsing failed" },
        { status: err.response.status },
      )
    }
    return NextResponse.json(
      {
        error: "IntentParser unreachable",
        detail: "Start the BAP server: python -m src.server (from Bap-1/)",
      },
      { status: 502 },
    )
  }
}
