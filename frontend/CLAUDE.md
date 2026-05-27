# Frontend — CLAUDE.md

> Read this before touching any UI file. It governs every decision.

## Stack

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js 13 (App Router, RSC + "use client" islands) | 13.5.6 |
| UI Library | shadcn/ui (style: "default", baseColor: "slate") | — |
| Styling | Tailwind CSS 3.4 — CSS variable tokens via `hsl(var(--*))` | 3.4.1 |
| Icons | lucide-react | 1.8.0 |
| Charts | recharts (all dynamically imported, `ssr: false`) | 3.8.1 |
| Auth | next-auth 4 (stub credentials dev / Keycloak OIDC prod) | 4.24.14 |
| HTTP | axios — wrappers in `src/lib/api.ts` | 1.15.0 |
| State | React local state only (useState / useEffect) | — |
| Forms | Manually controlled inputs — no form library | — |
| TypeScript | Strict mode | 5 |

## Repo Conventions

- **Language:** All user-visible UI copy must be in **English**. Code, comments, and git commits also in English.
- **Component placement:** shared primitives → `src/components/ui/`; feature components → `src/components/<feature>/`; layout → `src/components/layout/`.
- **Dynamic imports:** every recharts component must use `dynamic(..., { ssr: false })`. Never import recharts at the top level of a page.
- **shadcn first:** always use an existing shadcn primitive before writing a raw HTML element. Check `src/components/ui/` before adding `<button>`, `<table>`, `<dialog>`, etc.
- **No new dependencies** without explicit user approval.
- **No full component rewrites** when a targeted fix is sufficient.
- **No product copy / i18n changes** without consulting the user.

## Accessibility — Non-negotiable (WCAG 2.1 AA)

Every change must preserve or improve accessibility. Mandatory checks before any PR:

1. **Heading hierarchy:** h1 → h2 → h3 in strict order. `CardTitle` renders as `<h3>` — there must be an `<h2>` above it on every page.
2. **Focus visible:** all interactive elements must show a visible focus ring. Use `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2` (matches shadcn pattern). Never remove outlines without a replacement.
3. **Accessible names:** every icon-only button needs `aria-label`. Decorative icons need `aria-hidden="true"`.
4. **Dynamic announcements:** errors, success messages, and loading states that appear without page reload need `role="alert"` or `aria-live="polite"`.
5. **Keyboard navigation:** all interactive elements reachable and operable via Tab / Enter / Space / Arrow keys. No hover-only interactions.
6. **Color contrast:** minimum 4.5:1 for normal text, 3:1 for large text and UI components (WCAG AA).
7. **Charts:** every recharts SVG needs a wrapping `<div role="img" aria-label="...">` and an empty-state guard with `role="status"`.
8. **Skip link:** `<a href="#main-content">` must be the first focusable element in the layout.
9. **Landmarks:** `<nav>` in Navbar, `<main id="main-content">` in every page shell.

## Visual Design Patterns (established)

These patterns are already in use — apply them consistently:

- **Section header accent bar:**
  ```tsx
  <div className="flex items-center gap-2 mb-4">
    <span className="h-5 w-1 rounded-full bg-primary shrink-0" aria-hidden="true" />
    <h2 className="text-sm font-semibold text-foreground">Section Name</h2>
  </div>
  ```
- **KPI value:** `text-3xl font-bold tabular-nums leading-none mt-1`
- **Icon container:** `rounded-md bg-primary/10 p-2 text-primary`
- **Interactive card:** `transition-shadow hover:shadow-md`
- **Empty state:** `role="status"` + thematic lucide icon at `h-8 w-8 opacity-30 aria-hidden="true"` + description span

## Beckn Protocol Context

This is a B2B enterprise procurement agent. The UI is dense by design:
- Tables, long forms, multi-step flows, dashboards are the norm.
- Users are procurement officers, approvers, and admins — not consumers.
- Transactions involve real money and legal commitments — error states and confirmation dialogs are safety-critical, not just polish.

## Skill Reference

When working on this frontend, apply these skills as mandatory guidance:

- **`ux-heuristics`** — use for any behavioral, copy, or interaction change (Nielsen #1–10, Krug's 3 laws, Quick Diagnostic).
- **`refactoring-ui`** — use for any visual change (spacing, color, typography, component redesign).

Always score the affected screen before and after changes using the ux-heuristics 0–10 scale.

## Known Issues (do not regress)

- `AuthGuard.tsx` is dead code — do not reference it.
- Geist fonts exist in `src/app/fonts/` but are not registered — body uses Arial.
- `accent` and `muted` CSS tokens are identical — `accent` is effectively unused.
- No `loading.tsx`, `error.tsx`, or `not-found.tsx` defined anywhere (App Router boundaries missing).
- recharts charts have zero ARIA support — tracked as a systemic issue.
- No `.env.example` file — onboarding gap.
- No tests of any kind — zero Jest/Vitest/Playwright coverage.
