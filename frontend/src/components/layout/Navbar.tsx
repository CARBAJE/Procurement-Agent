"use client"

import { signOut, useSession } from "next-auth/react"
import Link from "next/link"
import { ShoppingCart, LogOut, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

const ROLE_COLORS: Record<string, "default" | "secondary" | "outline"> = {
  requester: "secondary",
  approver:  "default",
  admin:     "outline",
}

export default function Navbar() {
  const { data: session } = useSession()

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <Link href="/dashboard" className="flex items-center gap-2 font-semibold mr-6">
          <ShoppingCart className="h-5 w-5 text-primary" />
          <span>Procurement Agent</span>
        </Link>

        <nav className="flex items-center gap-4 text-sm flex-1">
          <Link href="/dashboard"    className="text-muted-foreground hover:text-foreground transition-colors">Dashboard</Link>
          <Link href="/request/new"  className="text-muted-foreground hover:text-foreground transition-colors">Nueva Solicitud</Link>
        </nav>

        {session?.user && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm">
              <User className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">{session.user.name}</span>
              <Badge variant={ROLE_COLORS[session.user.role] ?? "secondary"}>
                {session.user.role}
              </Badge>
            </div>
            <Button variant="ghost" size="sm" onClick={() => signOut({ callbackUrl: "/login" })}>
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
    </header>
  )
}
