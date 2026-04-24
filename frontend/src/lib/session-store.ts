// Client-side session state for the wizard flow.
// One composite blob per transaction_id survives navigation within the tab.
// Not durable across tab close — that's intentional (no PII persistence).
//
// TODO(persistence): if procurement sessions need to survive tab close or
// cross-device use, back this with a server-side GET /session/{txn_id} that
// reads from the same TransactionSessionStore the BAP already uses.
// See: Bap-1/docs/ARCHITECTURE.md §7.2 #6.

import type {
  BecknIntent,
  CommitResult,
  ComparisonResult,
} from "@/lib/types"

const KEY_PREFIX = "procurement:session:"

export interface WizardSession {
  intent: BecknIntent
  comparison: ComparisonResult
  chosenItemId: string | null
  commit: CommitResult | null
}

export function loadSession(txnId: string): WizardSession | null {
  if (typeof window === "undefined") return null
  try {
    const raw = sessionStorage.getItem(KEY_PREFIX + txnId)
    if (!raw) return null
    return JSON.parse(raw) as WizardSession
  } catch {
    return null
  }
}

export function saveSession(txnId: string, session: WizardSession): void {
  if (typeof window === "undefined") return
  try {
    sessionStorage.setItem(KEY_PREFIX + txnId, JSON.stringify(session))
  } catch {
    // sessionStorage may be full or disabled (private mode) — swallow.
  }
}

export function patchSession(
  txnId: string,
  patch: Partial<WizardSession>,
): WizardSession | null {
  const current = loadSession(txnId)
  if (!current) return null
  const merged = { ...current, ...patch }
  saveSession(txnId, merged)
  return merged
}

export function clearSession(txnId: string): void {
  if (typeof window === "undefined") return
  sessionStorage.removeItem(KEY_PREFIX + txnId)
}
