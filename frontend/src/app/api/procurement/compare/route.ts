import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  // Attach the authenticated Keycloak identity so the backend can JIT-provision
  // the user and attribute the request to them (not the System Agent).
  const actor = {
    keycloak_id: session.user.id,
    email:       session.user.email,
    name:        session.user.name,
    role:        session.user.role,
  }
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.post(`${bapUrl}/compare`, { ...body, actor })
    return NextResponse.json(data)
  } catch (err) {
    console.error("[compare proxy] BAP error:", err)
    return NextResponse.json(
      { error: "Unable to search for suppliers. Please try again." },
      { status: 502 },
    )
  }
}
