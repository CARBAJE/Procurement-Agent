import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import RunView from "@/components/procurement/RunView"

interface PageProps {
  params: { txn_id: string }
}

export default async function RunPage({ params }: PageProps) {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8 max-w-6xl">
        <RunView runId={params.txn_id} />
      </main>
    </>
  )
}
