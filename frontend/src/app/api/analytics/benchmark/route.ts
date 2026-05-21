import { NextResponse } from "next/server"
import type { BenchmarkReport } from "@/lib/types"

const MOCK_REPORT: BenchmarkReport = {
  generated_at: new Date().toISOString(),
  projected_annual_savings: 2_340_000,
  categories: [
    {
      category: "Office Supplies",
      current_contract: 850,
      best_market_price: 620,
      gap_percent: 27,
      annual_savings: 345_000,
      top_alternative: "OfficeDepot India",
    },
    {
      category: "IT Hardware",
      current_contract: 42_000,
      best_market_price: 36_500,
      gap_percent: 13,
      annual_savings: 660_000,
      top_alternative: "TechSource Pro",
    },
    {
      category: "Facility Services",
      current_contract: 120_000,
      best_market_price: 98_000,
      gap_percent: 18,
      annual_savings: 528_000,
      top_alternative: "CleanCo Enterprise",
    },
    {
      category: "Logistics",
      current_contract: 18_500,
      best_market_price: 14_200,
      gap_percent: 23,
      annual_savings: 516_000,
      top_alternative: "SwiftShip B2B",
    },
    {
      category: "Raw Materials",
      current_contract: 210_000,
      best_market_price: 196_000,
      gap_percent: 7,
      annual_savings: 168_000,
      top_alternative: "MatSupply Co",
    },
    {
      category: "Marketing & Print",
      current_contract: 55_000,
      best_market_price: 40_000,
      gap_percent: 27,
      annual_savings: 180_000,
      top_alternative: "PrintWorks India",
    },
  ],
}

export async function GET() {
  return NextResponse.json(MOCK_REPORT)
}
