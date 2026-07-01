// Next.js proxy → Dynamic Mock Gateway (`services/frontend_demo_gateway`).
//
// Forwards the front-end's score payload to the Python gateway, which runs
// the real Phase-2 `nn.Linear` LTR model. The gateway URL is configurable
// via the DEMO_GATEWAY_URL environment variable; see
// `frontend/.env.development.local.example` for the documented dev setup.
//
// This route deliberately bypasses NextAuth because the demo gateway is a
// local development tool — production deployment should re-add the
// `getServerSession` guard the sibling `/api/procurement/*` routes use.
import { NextRequest, NextResponse } from "next/server"
import axios from "axios"

export async function POST(req: NextRequest) {
  const body = await req.json()
  const gatewayUrl = process.env.DEMO_GATEWAY_URL ?? "http://localhost:8005"

  try {
    const { data } = await axios.post(`${gatewayUrl}/api/demo/score`, body)
    return NextResponse.json(data)
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[demo/score proxy] gateway error:", err)
    return NextResponse.json(
      { error: "Scoring service is temporarily unavailable. Please try again." },
      { status: 502 },
    )
  }
}
