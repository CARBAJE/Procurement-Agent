"use client"

import Navbar from "@/components/layout/Navbar"
import { NegotiationStepper } from "@/components/procurement/NegotiationStepper"

export default function NegotiationPage() {
  return (
    <>
      <Navbar />
      <main id="main-content" className="mx-auto max-w-4xl px-4 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">
            Autonomous Negotiation
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Watch the buyer agent (LangGraph engine) negotiate live against a
            local qwen3:8b supplier agent — real LLM responses, real policy
            guardrails, no scripted outcomes.
          </p>
        </header>
        <NegotiationStepper />
      </main>
    </>
  )
}
