# Procurement Agent — Frontend

Next.js 13 App Router + NextAuth + Tailwind + shadcn-style components. The user-facing layer of the Beckn Procurement Agent.

## What you can do here

1. **Log in** (`/login`) — stub SSO with 3 demo users (requester / approver / admin). Swap-ready for Keycloak OIDC.
2. **Create a request** (`/request/new`) — enter a natural-language procurement query. The Intent Parser (Ollama) converts it to a structured `BecknIntent`.
3. **Compare offers** (`/request/[txn_id]/compare`) — side-by-side table of the offerings returned by the Beckn network, sortable by price / rating / delivery time / stock. Agent scoring + reasoning trace visible. Keyboard navigation (↑↓ Enter). Pick a non-recommended option → confirmation dialog with a diff against the agent's pick.
4. **Track an order** (`/request/[txn_id]/order`) — order summary, lifecycle timeline (CREATED → ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED), HTTP status polling every 30 s. Swap-ready for a WebSocket backend.

## Architecture at a glance

```
                      ┌──────────────────────┐
                      │  Browser (React)      │
                      └──────────┬────────────┘
                                 │
                ┌────────────────▼─────────────────┐
                │  Next.js App Router (:3000)       │
                │  Server Components + API proxies  │
                └────────────────┬──────────────────┘
                                 │ (session-guarded)
                                 ▼
                      ┌──────────────────────┐
                      │  BAP Server (:8000)   │
                      │  Python aiohttp       │
                      └──────────┬────────────┘
                                 │
                                 ▼
                      Beckn network (ONIX + BPPs)
```

## Directory layout

```
src/
├── app/
│   ├── login/page.tsx                       NextAuth credentials login (stub users)
│   ├── dashboard/page.tsx                   Home / request list (placeholder metrics today)
│   ├── request/
│   │   ├── new/page.tsx                     Natural-language query form
│   │   └── [txn_id]/
│   │       ├── compare/page.tsx             Side-by-side comparison view
│   │       └── order/page.tsx               Order summary + timeline + polling
│   └── api/procurement/
│       ├── parse/route.ts                   Proxy → Python /parse (no mock fallback)
│       ├── compare/route.ts                 Proxy → Python /compare
│       ├── commit/route.ts                  Proxy → Python /commit
│       └── status/[txn_id]/[order_id]/route.ts   Proxy → Python /status
├── components/
│   ├── layout/Navbar.tsx
│   ├── auth/LoginForm.tsx · AuthGuard.tsx
│   ├── procurement/
│   │   ├── ProcurementForm.tsx              NL input + IntentPreview step
│   │   ├── IntentPreview.tsx                Shows parsed BecknIntent + confidence
│   │   ├── CompareView.tsx                  Client component for /compare route
│   │   ├── ComparisonTable.tsx              Sortable + keyboard-navigable table
│   │   ├── OfferCard.tsx · CriterionBar.tsx
│   │   ├── ScoringPanel.tsx                 "Why this is recommended" panel
│   │   ├── ReasoningPanel.tsx               Agent trace (purple/orange/green ReAct roles)
│   │   ├── ConfirmCommitDialog.tsx          Diff vs recommended (Radix Dialog)
│   │   ├── OrderView.tsx                    Client component for /order route
│   │   ├── OrderSummaryCard.tsx
│   │   ├── OrderLifecycleTimeline.tsx
│   │   └── StatusPoller.tsx                 30 s polling, swap-ready for WebSocket
│   └── ui/                                  shadcn primitives (local copies)
├── lib/
│   ├── types.ts                             BecknIntent, Offering, ComparisonResult, …
│   ├── api.ts                               axios helpers for /parse /compare /commit /status
│   ├── session-store.ts                     sessionStorage wrapper for the wizard state
│   ├── auth.ts                              NextAuth config + stub users
│   └── utils.ts                             cn() classname merger
└── app/globals.css                          HSL theme tokens, dark-mode-aware
```

## Wizard session state

Between routes (`/request/new` → `/compare` → `/order`), state lives in a single `sessionStorage` blob keyed by `transaction_id`:

```ts
interface WizardSession {
  intent: BecknIntent            // from /parse
  comparison: ComparisonResult   // from /compare
  chosenItemId: string | null    // user's pick (may differ from recommended)
  commit: CommitResult | null    // populated after /commit
}
```

Use `loadSession(txnId)`, `saveSession(txnId, s)`, `patchSession(txnId, patch)` from `src/lib/session-store.ts`. Clears on tab close by design — no PII persists.

## Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 13.5 (App Router) |
| Language | TypeScript strict |
| Auth | NextAuth 4 (JWT + CredentialsProvider, stub — swap to Keycloak later) |
| HTTP | axios |
| Styling | Tailwind CSS 3 + `tailwindcss-animate` |
| Components | shadcn-style (Radix primitives + CVA + Lucide icons) |
| State | React `useState` (no Redux / Zustand / SWR — YAGNI) |
| Polling | `setInterval` in `StatusPoller` (swap-ready for WebSocket) |

## Run

```bash
npm install
npm run dev        # :3000 — requires BAP backend on :8000
npm run build      # production build — 11 routes compiled
npm run lint
```

The Python BAP server on `:8000` handles `/parse`, `/compare`, `/commit`, `/status`. When the BAP is offline, Next.js proxies return `502` and the UI shows the error verbatim — **there is no silent mock fallback**. To verify the backend is up: `curl http://localhost:8000/health`.

## Environment

```
# .env.local
BAP_URL=http://localhost:8000                  # where all proxy routes call
INTENT_PARSER_URL=http://localhost:8000        # same process today
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=procurement-agent-secret-phase1
```

## What's stubbed / deliberately incomplete

See `Bap-1/docs/ARCHITECTURE.md §7` for the full catalog. Frontend-specific items:

- **Auth**: 3 hardcoded users in `src/lib/auth.ts` — swap to Keycloak before production.
- **Status polling**: `setInterval(30s)`. Interface on `StatusPoller` is designed for swap to WebSocket (`onUpdate(StatusSnapshot)`).
- **No frontend tests yet** — per milestone decision. Manual validation in browser covers the wizard. Vitest + RTL is the next step when the UI scope grows.
- **`Dashboard` metrics cards** are static placeholders. Real data needs a backend list endpoint (out of scope for Milestone 2).

## Related docs

- `Bap-1/README.md` — backend overview and quickstart.
- `Bap-1/docs/ARCHITECTURE.md` — full system architecture, diagrams, and production blockers (§7).
- `Bap-1/CLAUDE.md` — protocol gotchas + code guidance (also read by Claude Code).
- `docs/sequence-diagrams.md` (this folder) — end-to-end sequence diagrams per flow.
