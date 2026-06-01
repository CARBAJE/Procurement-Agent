import type { UserRole } from "@/lib/types"

declare module "next-auth" {
  interface Session {
    user: {
      id?: string
      name?: string | null
      email?: string | null
      image?: string | null
      role: UserRole
    }
  }
  interface User {
    role: UserRole
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role: UserRole
    // Keycloak `sub` claim — used to link the IdP user to our local
    // `users.keycloak_id` row when JIT provisioning lands.
    kcSub?: string
    // Persisted id_token so the federated logout route can pass it as
    // `id_token_hint` to Phase Two's end_session_endpoint.
    idToken?: string
  }
}
