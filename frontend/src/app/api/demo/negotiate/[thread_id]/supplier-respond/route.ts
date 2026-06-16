// Next.js proxy → Dynamic Mock Gateway supplier-respond endpoint.
//
// Asks the gateway's qwen3:8b Supplier Agent to respond to the buyer
// graph's current counter-offer. The gateway publishes the supplier reply
// to Redis, resuming the parked LangGraph buyer thread for the next round.
// The UI calls this once per round whenever `awaiting_supplier` is true.
import { NextRequest, NextResponse } from "next/server"
import axios from "axios"

export async function POST(
  _req: NextRequest,
  { params }: { params: { thread_id: string } },
) {
  const gatewayUrl = process.env.DEMO_GATEWAY_URL ?? "http://localhost:8005"
  const threadId = encodeURIComponent(params.thread_id)

  try {
    const { data, status } = await axios.post(
      `${gatewayUrl}/api/demo/negotiate/${threadId}/supplier-respond`,
      {},
      { validateStatus: (s) => s < 500, timeout: 90_000 },
    )
    return NextResponse.json(data, { status })
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[demo/negotiate/:thread_id/supplier-respond proxy] gateway error:", err)
    return NextResponse.json(
      { error: "Demo gateway unavailable" },
      { status: 502 },
    )
  }
}
