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
    const { data } = await axios.post(`${bapUrl}/commit`, body)
    return NextResponse.json(data)
  } catch (err) {
    // axios wraps non-2xx responses; surface the original status + detail.
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[commit proxy] BAP error:", err)
    return NextResponse.json(
      {
        error: "BAP backend unavailable",
        detail: "Start it with: python -m src.server (from Bap-1/)",
      },
      { status: 502 },
    )
  }
}
