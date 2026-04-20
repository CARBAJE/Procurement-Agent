import type { UserRole } from "@/lib/types"

declare module "next-auth" {
  interface Session {
    user: {
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
  }
}
