import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import NegotiateView from "@/components/procurement/NegotiateView"

interface PageProps {
  params: { txn_id: string }
  searchParams: Record<string, string | string[] | undefined>
}

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v
}

export default async function NegotiatePage({ params, searchParams }: PageProps) {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  const listPriceRaw = one(searchParams.original_price)
  const quantityRaw = one(searchParams.quantity)

  return (
    <>
      <Navbar />
      <main id="main-content" className="container py-8 max-w-4xl">
        <NegotiateView
          txnId={params.txn_id}
          supplierId={one(searchParams.supplier_id)}
          supplierName={one(searchParams.supplier_name)}
          itemId={one(searchParams.item_id)}
          item={one(searchParams.item)}
          quantity={quantityRaw ? Number(quantityRaw) : undefined}
          listPrice={listPriceRaw ? Number(listPriceRaw) : undefined}
          deliveryDate={one(searchParams.delivery_date)}
        />
      </main>
    </>
  )
}
