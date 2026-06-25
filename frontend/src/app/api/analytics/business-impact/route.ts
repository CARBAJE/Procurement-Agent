import { NextResponse } from "next/server"

const ANALYTICS_URL = process.env.ANALYTICS_URL ?? "http://localhost:8009"

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const period = searchParams.get("period") ?? "90d"

  try {
    const res = await fetch(`${ANALYTICS_URL}/business-impact?period=${period}`, {
      cache: "no-store",
    })
    if (!res.ok) {
      return NextResponse.json({ error: "unavailable" }, { status: 503 })
    }
    return NextResponse.json(await res.json())
  } catch {
    return NextResponse.json({ error: "unavailable" }, { status: 503 })
  }
}
