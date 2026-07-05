import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const actor = {
    keycloak_id: session.user.id,
    email:       session.user.email,
    name:        session.user.name,
    role:        session.user.role,
  }
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.post(`${bapUrl}/run`, { ...body, actor })
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[run proxy] orchestrator error:", err)
    return NextResponse.json(
      { error: "Unable to start procurement run. Please try again." },
      { status: 502 },
    )
  }
}
