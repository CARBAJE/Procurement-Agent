"use client"

import { useState } from "react"
import { signIn } from "next-auth/react"
import { useSearchParams } from "next/navigation"
import { Loader2, ShoppingCart, LogIn } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const ERROR_MESSAGES: Record<string, string> = {
  Configuration:    "Authentication is not configured correctly. Please contact support.",
  AccessDenied:     "Access denied. Your account does not have permission to sign in.",
  Verification:     "Verification link expired. Please try signing in again.",
  OAuthSignin:      "Could not start the sign-in flow. Please try again.",
  OAuthCallback:    "Could not complete the sign-in flow. Please try again.",
  OAuthCreateAccount: "Could not create your account. Please contact support.",
  Callback:         "Sign-in failed. Please try again.",
  Default:          "Sign-in failed. Please try again.",
}

export default function LoginForm() {
  const searchParams = useSearchParams()
  const errorCode = searchParams.get("error")
  const errorMessage = errorCode ? (ERROR_MESSAGES[errorCode] ?? ERROR_MESSAGES.Default) : null

  const [loading, setLoading] = useState(false)

  async function handleSignIn() {
    setLoading(true)
    await signIn("keycloak", { callbackUrl: "/" })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-md space-y-4">
        <div className="flex items-center justify-center gap-3 mb-2">
          <div className="rounded-md bg-primary/10 p-2 text-primary">
            <ShoppingCart className="h-6 w-6" aria-hidden="true" />
          </div>
          <h1 className="text-2xl font-bold">Procurement Agent</h1>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>
              You will be redirected to your organization&apos;s identity
              provider to authenticate.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {errorMessage && (
              <p
                role="alert"
                tabIndex={-1}
                className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {errorMessage}
              </p>
            )}

            <Button
              type="button"
              className="w-full"
              onClick={handleSignIn}
              disabled={loading}
              aria-label="Sign in with Phase Two"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Redirecting…
                </>
              ) : (
                <>
                  <LogIn className="mr-2 h-4 w-4" aria-hidden="true" />
                  Sign in with Phase Two
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
