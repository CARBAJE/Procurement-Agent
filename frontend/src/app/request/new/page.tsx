import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import ProcurementForm from "@/components/procurement/ProcurementForm"

export default async function NewRequestPage() {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  return (
    <>
      <Navbar />
      <main className="container py-8 max-w-5xl">
        <ProcurementForm />
      </main>
    </>
  )
}
