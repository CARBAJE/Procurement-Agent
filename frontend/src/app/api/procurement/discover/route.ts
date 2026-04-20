import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.post(`${bapUrl}/discover`, body)
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({
      transaction_id: "mock-txn-" + Date.now(),
      offerings: [],
      status: "mock",
      error: "BAP backend unavailable (python -m src.server not running)",
    })
  }
}
