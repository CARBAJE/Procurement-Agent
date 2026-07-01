import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  if (session.user.role === "admin") {
    return NextResponse.json(
      { error: "Forbidden — admin role cannot place orders" },
      { status: 403 },
    )
  }

  const body = await req.json()
  // Carry the authenticated identity (the requester is resolved from the
  // session at /compare; included here for symmetry / future approver use).
  const actor = {
    keycloak_id: session.user.id,
    email:       session.user.email,
    name:        session.user.name,
    role:        session.user.role,
  }
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.post(`${bapUrl}/commit`, { ...body, actor })
    return NextResponse.json(data)
  } catch (err) {
    // axios wraps non-2xx responses; surface the original status + detail.
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[commit proxy] BAP error:", err)
    return NextResponse.json(
      { error: "Unable to place your order. Please try again." },
      { status: 502 },
    )
  }
}
