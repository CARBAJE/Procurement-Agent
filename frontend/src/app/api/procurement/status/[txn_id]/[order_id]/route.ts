import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function GET(
  req: NextRequest,
  { params }: { params: { txn_id: string; order_id: string } },
) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const search = req.nextUrl.searchParams.toString()
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  const target = `${bapUrl}/status/${encodeURIComponent(params.txn_id)}/${encodeURIComponent(params.order_id)}${search ? `?${search}` : ""}`
  try {
    const { data } = await axios.get(target)
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[status proxy] BAP error:", err)
    return NextResponse.json(
      {
        error: "BAP backend unavailable",
        detail: "Start it with: python -m src.server (from Bap-1/)",
      },
      { status: 502 },
    )
  }
}
