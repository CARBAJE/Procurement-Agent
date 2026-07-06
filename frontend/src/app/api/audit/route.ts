import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

const DATA_NORMALIZER_URL =
  process.env.DATA_NORMALIZER_URL ?? "http://localhost:8006"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = req.nextUrl
  const requestId = searchParams.get("request_id")
  const poId      = searchParams.get("po_id")
  const limit     = searchParams.get("limit") ?? "100"

  if (!requestId && !poId) {
    return NextResponse.json(
      { error: "request_id or po_id query parameter is required" },
      { status: 400 },
    )
  }

  const params = new URLSearchParams({ limit })
  if (requestId) params.set("request_id", requestId)
  else if (poId)  params.set("po_id", poId)

  try {
    const { data } = await axios.get(
      `${DATA_NORMALIZER_URL}/normalize/audit?${params.toString()}`,
    )
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[audit proxy] data-normalizer error:", err)
    return NextResponse.json({ error: "data-normalizer unavailable" }, { status: 502 })
  }
}
