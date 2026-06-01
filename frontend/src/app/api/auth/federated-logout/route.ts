import { NextResponse, type NextRequest } from "next/server"
import { getToken } from "next-auth/jwt"

const NEXT_AUTH_COOKIES = [
  "next-auth.session-token",
  "next-auth.csrf-token",
  "next-auth.callback-url",
  "__Secure-next-auth.session-token",
  "__Host-next-auth.csrf-token",
  "__Secure-next-auth.callback-url",
]

function clearAuthCookies(res: NextResponse): NextResponse {
  for (const name of NEXT_AUTH_COOKIES) {
    res.cookies.set({ name, value: "", path: "/", maxAge: 0 })
  }
  return res
}

export async function GET(req: NextRequest) {
  const loginUrl = new URL("/login", req.url)
  const issuer   = process.env.KEYCLOAK_ISSUER

  const token = await getToken({ req })
  const idTokenHint = token?.idToken as string | undefined

  if (!idTokenHint || !issuer) {
    return clearAuthCookies(NextResponse.redirect(loginUrl))
  }

  const endSession = new URL(`${issuer.replace(/\/$/, "")}/protocol/openid-connect/logout`)
  endSession.searchParams.set("id_token_hint", idTokenHint)
  endSession.searchParams.set("post_logout_redirect_uri", loginUrl.toString())

  return clearAuthCookies(NextResponse.redirect(endSession))
}
