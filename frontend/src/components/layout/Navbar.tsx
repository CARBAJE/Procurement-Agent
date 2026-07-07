"use client"

import { useSession } from "next-auth/react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Zap, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const NAV_LINKS = [
  { href: "/",            label: "Home" },
  { href: "/dashboard",   label: "Dashboard" },
  { href: "/request/new", label: "New Request" },
]

const ROLE_COLORS: Record<string, "default" | "secondary" | "outline"> = {
  requester: "secondary",
  approver:  "default",
  admin:     "outline",
}

export default function Navbar() {
  const { data: session } = useSession()
  const pathname = usePathname()
  const role = session?.user.role

  return (
    <header className="sticky top-0 z-50 w-full bg-white/80 backdrop-blur-xl border-b border-border/50">
      <div className="container flex h-14 items-center gap-8">
        <Link
          href="/"
          className="flex items-center gap-2 shrink-0 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-label="Procurement Agent home"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Zap className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="font-black tracking-tighter text-foreground">Procurement</span>
        </Link>

        <nav className="flex items-center gap-1 flex-1" aria-label="Main navigation">
          {NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href + "/"))
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  active
                    ? "text-primary font-semibold bg-primary/10"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary",
                )}
              >
                {label}
              </Link>
            )
          })}

          {(role === "approver" || role === "admin") && (
            <Link
              href="/approvals"
              aria-current={pathname.startsWith("/approvals") ? "page" : undefined}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                pathname.startsWith("/approvals")
                  ? "text-primary font-semibold bg-primary/10"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary",
              )}
            >
              Approvals
            </Link>
          )}

          {role === "admin" && (
            <Link
              href="/admin"
              aria-current={pathname.startsWith("/admin") ? "page" : undefined}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                pathname.startsWith("/admin")
                  ? "text-primary font-semibold bg-primary/10"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary",
              )}
            >
              Admin
            </Link>
          )}
        </nav>

        {session?.user && (
          <div className="flex items-center gap-2 shrink-0">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground hidden sm:block">{session.user.name}</span>
              <Badge variant={ROLE_COLORS[session.user.role] ?? "secondary"} className="text-xs">
                {session.user.role}
              </Badge>
            </div>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Sign out"
              onClick={() => { window.location.href = "/api/auth/federated-logout" }}
              className="text-muted-foreground hover:text-foreground"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        )}
      </div>
    </header>
  )
}
