import { redirect } from "next/navigation"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Navbar from "@/components/layout/Navbar"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PlusCircle, Clock, CheckCircle, AlertCircle } from "lucide-react"

export default async function DashboardPage() {
  const session = await getServerSession(authOptions)
  if (!session) redirect("/login")

  return (
    <>
      <Navbar />
      <main className="container py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">Dashboard</h1>
            <p className="text-muted-foreground">Bienvenido, {session.user.name}</p>
          </div>
          <Button asChild>
            <Link href="/request/new">
              <PlusCircle className="mr-2 h-4 w-4" />
              Nueva Solicitud
            </Link>
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-3 mb-8">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Solicitudes Activas</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">0</div>
              <p className="text-xs text-muted-foreground">Pendientes de respuesta</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Completadas</CardTitle>
              <CheckCircle className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">0</div>
              <p className="text-xs text-muted-foreground">Este mes</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Pendientes Aprobación</CardTitle>
              <AlertCircle className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">0</div>
              <p className="text-xs text-muted-foreground">Requieren revisión</p>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Solicitudes Recientes</CardTitle>
            <CardDescription>Historial de tus últimas solicitudes de compra</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <PlusCircle className="h-12 w-12 text-muted-foreground/40 mb-4" />
              <p className="text-muted-foreground font-medium">No hay solicitudes aún</p>
              <p className="text-sm text-muted-foreground mb-4">
                Crea tu primera solicitud de compra usando lenguaje natural
              </p>
              <Button asChild variant="outline">
                <Link href="/request/new">Crear primera solicitud</Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        {session.user.role !== "requester" && (
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              Rol: {session.user.role} — funcionalidades adicionales disponibles en fases posteriores
            </Badge>
          </div>
        )}
      </main>
    </>
  )
}
