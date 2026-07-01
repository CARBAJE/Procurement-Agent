import { NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"

const ANALYTICS_URL = process.env.ANALYTICS_URL ?? "http://localhost:8009"

export async function GET(request: Request) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const { searchParams } = new URL(request.url)
  const period = searchParams.get("period") ?? "90d"

  try {
    const res = await fetch(`${ANALYTICS_URL}/benchmark?period=${period}`, {
      cache: "no-store",
    })
    if (!res.ok) {
      return NextResponse.json(
        { error: "analytics_unavailable", status: res.status },
        { status: res.status },
      )
    }
    const data = await res.json()
    return NextResponse.json({ ...data, generated_at: new Date().toISOString() })
  } catch {
    return NextResponse.json(
      { error: "analytics_unavailable" },
      { status: 503 },
    )
  }
}
