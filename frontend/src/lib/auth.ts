import type { NextAuthOptions } from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"
import type { StubUser, UserRole } from "@/lib/types"

const STUB_USERS: StubUser[] = [
  { id: "1", name: "Priya Sharma",  email: "priya@example.com",  role: "requester" },
  { id: "2", name: "Rajesh Menon",  email: "rajesh@example.com", role: "approver"  },
  { id: "3", name: "Admin User",    email: "admin@example.com",  role: "admin"     },
]

const STUB_PASSWORDS: Record<string, string> = {
  "priya@example.com":  "requester123",
  "rajesh@example.com": "approver123",
  "admin@example.com":  "admin123",
}

// Phase 1 stub — replace CredentialsProvider with Keycloak OIDC in production
export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      credentials: {
        email:    { label: "Email",    type: "email"    },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email    = credentials?.email    as string
        const password = credentials?.password as string
        if (!email || !password)             return null
        if (STUB_PASSWORDS[email] !== password) return null
        return STUB_USERS.find((u) => u.email === email) ?? null
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.role = (user as StubUser).role
      return token
    },
    async session({ session, token }) {
      if (session.user) session.user.role = token.role as UserRole
      return session
    },
  },
  pages: { signIn: "/login" },
  session: { strategy: "jwt" },
}
