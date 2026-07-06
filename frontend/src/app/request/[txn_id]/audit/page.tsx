import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import AuditTrailView from "@/components/procurement/AuditTrailView"

interface PageProps {
  params: { txn_id: string }
}

export default async function AuditTrailPage({ params }: PageProps) {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8 max-w-4xl">
        <AuditTrailView requestId={params.txn_id} />
      </main>
    </>
  )
}
