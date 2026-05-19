import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"

const BAP_URL = process.env.BAP_URL ?? "http://localhost:8000"

const VALID_PERIODS = new Set(["30d", "90d", "180d"])

export async function GET(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { searchParams } = new URL(request.url)
  const period = VALID_PERIODS.has(searchParams.get("period") ?? "")
    ? (searchParams.get("period") as string)
    : "90d"

  try {
    const url = `${BAP_URL}/analytics?period=${period}&role=${encodeURIComponent(session.user.role)}`
    const res = await fetch(url, { cache: "no-store" })
    if (!res.ok) {
      return NextResponse.json({ error: "Backend error" }, { status: res.status })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: "Backend unavailable" }, { status: 503 })
  }
}
