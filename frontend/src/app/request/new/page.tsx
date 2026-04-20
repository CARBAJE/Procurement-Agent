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
      <main className="container py-8 max-w-2xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Nueva Solicitud</h1>
          <p className="text-muted-foreground">
            Describe en lenguaje natural qué necesitas comprar
          </p>
        </div>
        <ProcurementForm />
      </main>
    </>
  )
}
