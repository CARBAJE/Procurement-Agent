import { withAuth } from "next-auth/middleware"
import { NextResponse } from "next/server"

export default withAuth(
  function middleware(req) {
    const { pathname } = req.nextUrl
    const role = req.nextauth.token?.role as string | undefined

    if (pathname.startsWith("/approvals") && role !== "approver" && role !== "admin") {
      return NextResponse.redirect(new URL("/dashboard", req.url))
    }
    if (pathname.startsWith("/admin") && role !== "admin") {
      return NextResponse.redirect(new URL("/dashboard", req.url))
    }
  },
  {
    callbacks: {
      authorized: ({ token }) => !!token,
    },
  },
)

export const config = {
  matcher: ["/dashboard/:path*", "/approvals/:path*", "/admin/:path*", "/request/:path*"],
}
