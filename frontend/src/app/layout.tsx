import type { Metadata } from "next"
import { Manrope } from "next/font/google"
import { getServerSession } from "next-auth/next"
import { authOptions } from "@/lib/auth"
import Providers from "@/components/Providers"
import "./globals.css"

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
  weight: ["300", "400", "500", "600", "700", "800"],
  display: "swap",
})

export const metadata: Metadata = {
  title: "Procurement Agent",
  description: "Agentic AI Procurement on Beckn Protocol",
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions)
  return (
    <html lang="en" className={manrope.variable}>
      <body className="antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded focus:bg-background focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:shadow-md focus:ring-2 focus:ring-ring"
        >
          Skip to main content
        </a>
        <Providers session={session}>{children}</Providers>
      </body>
    </html>
  )
}
