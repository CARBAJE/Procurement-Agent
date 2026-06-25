import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth/next"
import axios from "axios"
import { authOptions } from "@/lib/auth"

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  if (session.user.role !== "admin") {
    return NextResponse.json({ error: "Forbidden — admin role required" }, { status: 403 })
  }

  const body = await req.json()
  const bapUrl = process.env.BAP_URL ?? "http://localhost:8000"
  try {
    const { data } = await axios.patch(
      `${bapUrl}/admin/users/${encodeURIComponent(params.id)}`,
      body,
    )
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    return NextResponse.json({ error: "BAP backend unavailable" }, { status: 502 })
  }
}
