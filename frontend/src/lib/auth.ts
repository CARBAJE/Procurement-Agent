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
        // Primary: realm_access.roles from ID token (requires "realm roles" mapper
        // with "Add to ID token: ON" in the Keycloak client scope).
        let realmRoles: string[] =
          (profile as { realm_access?: { roles?: string[] } }).realm_access?.roles ?? []

        // Fallback: decode the access_token, which always carries realm_access.roles
        // even when the ID token mapper is not configured.
        if (realmRoles.length === 0 && account.access_token) {
          try {
            const payload = JSON.parse(
              Buffer.from(account.access_token.split(".")[1], "base64url").toString(),
            )
            realmRoles = (payload as { realm_access?: { roles?: string[] } })
              .realm_access?.roles ?? []
          } catch {
            // malformed token — pickRole will default to "requester"
          }
        }

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
