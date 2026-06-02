import type { NextAuthOptions } from "next-auth"
import KeycloakProvider from "next-auth/providers/keycloak"
import type { UserRole } from "@/lib/types"

const KNOWN_ROLES: UserRole[] = ["admin", "approver", "requester"]

function pickRole(realmRoles: string[] = []): UserRole {
  return KNOWN_ROLES.find((r) => realmRoles.includes(r)) ?? "requester"
}

export const authOptions: NextAuthOptions = {
  providers: [
    KeycloakProvider({
      clientId:     process.env.KEYCLOAK_CLIENT_ID!,
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET!,
      issuer:       process.env.KEYCLOAK_ISSUER!,
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account && profile) {
        const realmRoles = (profile as { realm_access?: { roles?: string[] } })
          .realm_access?.roles ?? []
        token.role    = pickRole(realmRoles)
        token.kcSub   = (profile as { sub?: string }).sub
        token.idToken = account.id_token
      }
      return token
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.role = token.role as UserRole
        session.user.id   = token.kcSub as string | undefined
      }
      return session
    },
  },
  pages:   { signIn: "/login" },
  session: {
    strategy: "jwt",
    maxAge: 60 * 60 * 8,
  },
}
