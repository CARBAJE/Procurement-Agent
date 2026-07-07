import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const intentParserUrl = process.env.INTENT_PARSER_URL ?? "http://localhost:8001"
  try {
    const { data } = await axios.post(
      `${intentParserUrl}/explain-selection`,
      body,
      { timeout: 30_000 },
    )
    return NextResponse.json(data)
  } catch (err) {
    console.error("[explain-selection proxy] error:", err)
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(
        err.response.data ?? { error: "Explanation failed" },
        { status: err.response.status },
      )
    }
    return NextResponse.json({ error: "Unable to generate explanation." }, { status: 502 })
  }
}
