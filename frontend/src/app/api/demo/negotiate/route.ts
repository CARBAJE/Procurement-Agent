// Next.js proxy → Dynamic Mock Gateway negotiation endpoint.
//
// Forwards the front-end's negotiation payload to the Python gateway,
// which compiles the real Phase-3 LangGraph state machine and uses a
// BackgroundTask to simulate the asynchronous Beckn /on_select callback
// after 3 seconds. The client polls `/api/demo/negotiate/[thread_id]`
// to observe the interrupt → resume cycle in real time.
import { NextRequest, NextResponse } from "next/server"
import axios from "axios"

export async function POST(req: NextRequest) {
  const body = await req.json()
  const gatewayUrl = process.env.DEMO_GATEWAY_URL ?? "http://localhost:8005"

  try {
    const { data, status } = await axios.post(
      `${gatewayUrl}/api/demo/negotiate`,
      body,
      // Don't follow the 202 to anything else; surface it directly.
      { validateStatus: (s) => s < 500 },
    )
    return NextResponse.json(data, { status })
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[demo/negotiate proxy] gateway error:", err)
    return NextResponse.json(
      { error: "Negotiation service is temporarily unavailable. Please try again." },
      { status: 502 },
    )
  }
}
