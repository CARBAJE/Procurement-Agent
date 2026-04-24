import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import CompareView from "@/components/procurement/CompareView"

interface PageProps {
  params: { txn_id: string }
}

export default async function ComparePage({ params }: PageProps) {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  return (
    <>
      <Navbar />
      <main className="container py-8 max-w-6xl">
        <CompareView txnId={params.txn_id} />
      </main>
    </>
  )
}
