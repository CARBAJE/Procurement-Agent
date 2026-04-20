import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"

export default async function RootPage() {
  const session = await getServerSession(authOptions)
  redirect(session ? "/dashboard" : "/login")
}
