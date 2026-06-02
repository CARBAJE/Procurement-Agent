"use client"

import { useRef, useState } from "react"
import { signIn } from "next-auth/react"
import { useSearchParams } from "next/navigation"
import { Loader2, ShoppingCart, LogIn, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

// Friendly mapping for the next-auth error codes that can land in the URL
// when the OAuth callback fails. See https://next-auth.js.org/configuration/pages#error-codes.
const ERROR_MESSAGES: Record<string, string> = {
  Configuration:      "Authentication is not configured correctly. Please contact support.",
  AccessDenied:       "Access denied. Your account does not have permission to sign in.",
  Verification:       "Verification link expired. Please try signing in again.",
  OAuthSignin:        "Could not start the sign-in flow. Please try again.",
  OAuthCallback:      "Could not complete the sign-in flow. Please try again.",
  OAuthCreateAccount: "Could not create your account. Please contact support.",
  Callback:           "Sign-in failed. Please try again.",
  Default:            "Sign-in failed. Please try again.",
}

export default function LoginForm() {
  const searchParams = useSearchParams()
  const errorCode = searchParams.get("error")
  const errorMessage = errorCode ? (ERROR_MESSAGES[errorCode] ?? ERROR_MESSAGES.Default) : null

  const [loading, setLoading] = useState(false)
  const rootRef = useRef<HTMLElement>(null)

  // Track the cursor by writing CSS variables on the container — no React
  // re-render, so the follow-glow stays smooth. The glow layer reads
  // --mx / --my for its radial-gradient center.
  function handleMouseMove(e: React.MouseEvent<HTMLElement>) {
    const el = rootRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    el.style.setProperty("--mx", `${e.clientX - rect.left}px`)
    el.style.setProperty("--my", `${e.clientY - rect.top}px`)
  }

  async function handleSignIn() {
    setLoading(true)
    // Full-page redirect to Phase Two's hosted login. next-auth handles
    // state / PKCE / nonce. On success the browser returns to / via the
    // /api/auth/callback/keycloak endpoint.
    await signIn("keycloak", { callbackUrl: "/" })
  }

  return (
    <main
      ref={rootRef}
      id="main-content"
      onMouseMove={handleMouseMove}
      className="relative flex min-h-screen items-start justify-center overflow-hidden bg-background px-4 pb-12 pt-[12vh]"
    >
      {/* ── Decorative background: blueprint grid + signal-blue glow ── */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to right, hsl(var(--foreground) / 0.04) 1px, transparent 1px)," +
            "linear-gradient(to bottom, hsl(var(--foreground) / 0.04) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black 30%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black 30%, transparent 75%)",
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-[28rem] w-[28rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
      />

      {/* ── Cursor-following glow (desktop; hidden for reduced-motion) ── */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 motion-reduce:hidden"
        style={{
          background:
            "radial-gradient(380px circle at var(--mx, 50%) var(--my, 0%), hsl(var(--primary) / 0.13), transparent 65%)",
        }}
      />

      {/* ── Cursor-revealed grid: brighter signal-blue lines, aligned with
            the base grid (same 44px cell), masked to a circle around the
            cursor so the grid "lights up" only where the mouse is. ── */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 motion-reduce:hidden"
        style={{
          backgroundImage:
            "linear-gradient(to right, hsl(var(--primary) / 0.22) 1px, transparent 1px)," +
            "linear-gradient(to bottom, hsl(var(--primary) / 0.22) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage:
            "radial-gradient(300px circle at var(--mx, 50%) var(--my, 0%), rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.2) 45%, transparent 78%)",
          WebkitMaskImage:
            "radial-gradient(300px circle at var(--mx, 50%) var(--my, 0%), rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.2) 45%, transparent 78%)",
        }}
      />

      {/* ── Centered hero column ── */}
      <div className="relative z-10 w-full max-w-md space-y-8">
        {/* Brand lockup */}
        <div className="flex flex-col items-center text-center">
          <div className="rounded-2xl bg-primary/10 p-3 text-primary ring-1 ring-primary/15">
            <ShoppingCart className="h-7 w-7" aria-hidden="true" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-foreground">
            Procurement Agent
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Agentic procurement on the Beckn network
          </p>
        </div>

        {/* Sign-in card */}
        <Card className="rounded-2xl border-border/70 shadow-xl">
          <CardContent className="space-y-6 p-8">
            <div className="space-y-1.5">
              <h2 className="text-xl font-semibold tracking-tight text-foreground">
                Sign in to your account
              </h2>
              <p className="text-sm text-muted-foreground">
                Continue with your organization&apos;s identity provider.
              </p>
            </div>

            {errorMessage && (
              <p
                role="alert"
                tabIndex={-1}
                className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {errorMessage}
              </p>
            )}

            <Button
              type="button"
              size="lg"
              className="w-full text-base font-semibold shadow-sm transition-shadow hover:shadow-md"
              onClick={handleSignIn}
              disabled={loading}
              aria-label="Sign in with Phase Two"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" aria-hidden="true" />
                  Redirecting…
                </>
              ) : (
                <>
                  <LogIn className="mr-2 h-5 w-5" aria-hidden="true" />
                  Sign in with Phase Two
                </>
              )}
            </Button>

            <Separator />

            <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 shrink-0 text-primary/70" aria-hidden="true" />
              <span>you&apos;ll be redirected to authenticate.</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
