import axios from "axios"
import type { ParseResult } from "@/lib/types"

// Calls the Next.js API proxy → IntentParser backend
export async function parseIntent(query: string): Promise<ParseResult> {
  const { data } = await axios.post<ParseResult>("/api/procurement/parse", { query })
  return data
}

// Calls the Next.js API proxy → BAP backend /discover
export async function submitDiscovery(query: string): Promise<{ transaction_id: string }> {
  const { data } = await axios.post<{ transaction_id: string }>("/api/procurement/discover", { query })
  return data
}
