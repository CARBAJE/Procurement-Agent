import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function GET(
  _req: NextRequest,
  { params }: { params: { run_id: string } },
) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.get(
      `${bapUrl}/run/${encodeURIComponent(params.run_id)}`,
    )
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    return NextResponse.json({ error: "Run not found" }, { status: 502 })
  }
}
