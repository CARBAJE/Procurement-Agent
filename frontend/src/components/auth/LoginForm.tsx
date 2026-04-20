"use client"

import { useState } from "react"
import { signIn } from "next-auth/react"
import { useRouter } from "next/navigation"
import { Loader2, ShoppingCart } from "lucide-react"
import { Button }   from "@/components/ui/button"
import { Input }    from "@/components/ui/input"
import { Label }    from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

const DEMO_USERS = [
  { label: "Requester (Priya)", email: "priya@example.com",  password: "requester123" },
  { label: "Approver (Rajesh)", email: "rajesh@example.com", password: "approver123"  },
  { label: "Admin",             email: "admin@example.com",  password: "admin123"     },
]

export default function LoginForm() {
  const router = useRouter()
  const [email,    setEmail]    = useState("")
  const [password, setPassword] = useState("")
  const [error,    setError]    = useState("")
  const [loading,  setLoading]  = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    const result = await signIn("credentials", { email, password, redirect: false })
    setLoading(false)
    if (result?.error) {
      setError("Credenciales incorrectas. Usa uno de los usuarios de demo.")
    } else {
      router.push("/dashboard")
    }
  }

  function fillDemo(email: string, password: string) {
    setEmail(email)
    setPassword(password)
    setError("")
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-md space-y-4">
        <div className="flex items-center justify-center gap-2 mb-2">
          <ShoppingCart className="h-8 w-8 text-primary" />
          <h1 className="text-2xl font-bold">Procurement Agent</h1>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Iniciar sesión</CardTitle>
            <CardDescription>Ingresa tus credenciales para acceder al sistema de compras.</CardDescription>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="usuario@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Contraseña</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Entrar
              </Button>
            </form>
          </CardContent>

          <CardFooter className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground w-full">Usuarios de demo (Phase 1 SSO stub):</p>
            <div className="flex gap-2 w-full flex-wrap">
              {DEMO_USERS.map((u) => (
                <Button
                  key={u.email}
                  variant="outline"
                  size="sm"
                  type="button"
                  onClick={() => fillDemo(u.email, u.password)}
                  className="text-xs flex-1"
                >
                  {u.label}
                </Button>
              ))}
            </div>
          </CardFooter>
        </Card>
      </div>
    </div>
  )
}
