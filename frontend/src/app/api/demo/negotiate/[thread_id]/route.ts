// Next.js proxy → Dynamic Mock Gateway polling endpoint.
//
// The demo UI polls this every ~500 ms after kicking off a negotiation,
// watching for the moment the simulated /on_select callback fires and
// the LangGraph state machine resumes. The gateway's snapshot includes
// `resumed`, `final_outcome`, `current_counter_offer`, and `next` so the
// UI can show the full interrupt → resume → finalize transition visually.
import { NextRequest, NextResponse } from "next/server"
import axios from "axios"

export async function GET(
  _req: NextRequest,
  { params }: { params: { thread_id: string } },
) {
  const gatewayUrl = process.env.DEMO_GATEWAY_URL ?? "http://localhost:8005"
  const threadId = encodeURIComponent(params.thread_id)

  try {
    const { data, status } = await axios.get(
      `${gatewayUrl}/api/demo/negotiate/${threadId}`,
      { validateStatus: (s) => s < 500 },
    )
    return NextResponse.json(data, { status })
  } catch (err) {
    if (axios.isAxiosError(err) && err.response) {
      return NextResponse.json(err.response.data ?? {}, { status: err.response.status })
    }
    console.error("[demo/negotiate/:thread_id proxy] gateway error:", err)
    return NextResponse.json(
      { error: "Demo gateway unavailable" },
      { status: 502 },
    )
  }
}
