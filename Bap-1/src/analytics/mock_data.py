"""Deterministic mock analytics data for the dashboard.

Returns realistic procurement KPIs, spend trends, supplier metrics,
and recent request history. Used until PostgreSQL queries are wired up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_BASE_DATE = datetime(2026, 5, 18, tzinfo=timezone.utc)

_WEEKLY_SPENDS = [
    12400, 18500, 9800, 24300, 15600,
    8900, 21000, 16400, 11200, 19800,
    13500, 22100, 17300,
]

_SAVINGS_RATE = 0.083  # 8.3% savings from negotiation


def generate_mock_analytics(period: str = "90d") -> dict:
    period_days = {"30d": 30, "90d": 90, "180d": 180}.get(period, 90)
    weeks = max(1, period_days // 7)
    start_date = _BASE_DATE - timedelta(days=period_days)

    spend_data = []
    for i in range(weeks):
        week_start = start_date + timedelta(weeks=i)
        spend = _WEEKLY_SPENDS[i % len(_WEEKLY_SPENDS)]
        spend_data.append({
            "date": week_start.strftime("%b %d"),
            "spend": spend,
            "savings": round(spend * _SAVINGS_RATE, 2),
        })

    total_spend = sum(d["spend"] for d in spend_data)
    total_savings = sum(d["savings"] for d in spend_data)

    return {
        "kpis": {
            "total_spend": total_spend,
            "total_savings": round(total_savings, 2),
            "savings_percent": round(total_savings / total_spend * 100, 1) if total_spend else 0.0,
            "active_requests": 3,
            "completed_this_month": 12,
            "pending_approval": 2,
            "avg_cycle_time_hours": 4.2,
            "baseline_cycle_time_hours": 72.0,
            "active_suppliers": 6,
        },
        "spend_over_time": spend_data,
        "cycle_time_by_category": [
            {"category": "Office Supplies", "before_hours": 72,  "after_hours": 3.2},
            {"category": "IT Equipment",    "before_hours": 168, "after_hours": 8.5},
            {"category": "Lab Supplies",    "before_hours": 96,  "after_hours": 5.1},
            {"category": "Furniture",       "before_hours": 120, "after_hours": 12.3},
            {"category": "Marketing",       "before_hours": 48,  "after_hours": 2.8},
        ],
        "supplier_metrics": [
            {
                "bpp_id": "PROV-PAPERDIRECT-01",
                "provider_name": "PaperDirect India",
                "quality_score": 84,
                "delivery_score": 79,
                "price_competitiveness": 95,
                "compliance_score": 88,
                "total_orders": 24,
            },
            {
                "bpp_id": "PROV-OFFICEWORLD-01",
                "provider_name": "OfficeWorld Supplies",
                "quality_score": 96,
                "delivery_score": 94,
                "price_competitiveness": 72,
                "compliance_score": 95,
                "total_orders": 18,
            },
            {
                "bpp_id": "PROV-STATHUB-01",
                "provider_name": "Stationery Hub",
                "quality_score": 98,
                "delivery_score": 68,
                "price_competitiveness": 58,
                "compliance_score": 92,
                "total_orders": 9,
            },
            {
                "bpp_id": "PROV-GREENLEAF-01",
                "provider_name": "GreenLeaf Papers",
                "quality_score": 88,
                "delivery_score": 62,
                "price_competitiveness": 86,
                "compliance_score": 98,
                "total_orders": 14,
            },
            {
                "bpp_id": "PROV-QUICKPRINT-01",
                "provider_name": "QuickPrint Depot",
                "quality_score": 80,
                "delivery_score": 94,
                "price_competitiveness": 68,
                "compliance_score": 79,
                "total_orders": 11,
            },
            {
                "bpp_id": "PROV-BUDGETPAPER-01",
                "provider_name": "Budget Paper Co",
                "quality_score": 78,
                "delivery_score": 55,
                "price_competitiveness": 98,
                "compliance_score": 72,
                "total_orders": 7,
            },
        ],
        "recent_requests": [
            {
                "request_id": "req-a1b2c3d4",
                "raw_input_text": "100 reams A4 80gsm paper, Bangalore, 3 days delivery",
                "status": "confirmed",
                "category": "Office Supplies",
                "agreed_price": 16800.00,
                "currency": "INR",
                "created_at": "2026-05-15T10:23:00Z",
            },
            {
                "request_id": "req-b2c3d4e5",
                "raw_input_text": "500 sheets premium A4 paper for boardroom presentations",
                "status": "confirmed",
                "category": "Office Supplies",
                "agreed_price": 8500.00,
                "currency": "INR",
                "created_at": "2026-05-13T14:45:00Z",
            },
            {
                "request_id": "req-c3d4e5f6",
                "raw_input_text": "200 reams eco-friendly recycled A4 paper",
                "status": "confirmed",
                "category": "Office Supplies",
                "agreed_price": 36400.00,
                "currency": "INR",
                "created_at": "2026-05-10T09:15:00Z",
            },
            {
                "request_id": "req-d4e5f6g7",
                "raw_input_text": "Laptop accessories and peripherals for IT dept, 10 sets",
                "status": "pending_approval",
                "category": "IT Equipment",
                "agreed_price": None,
                "currency": "INR",
                "created_at": "2026-05-17T11:30:00Z",
            },
            {
                "request_id": "req-e5f6g7h8",
                "raw_input_text": "Monthly office stationery restocking — all departments",
                "status": "confirmed",
                "category": "Office Supplies",
                "agreed_price": 24300.00,
                "currency": "INR",
                "created_at": "2026-05-08T08:00:00Z",
            },
            {
                "request_id": "req-f6g7h8i9",
                "raw_input_text": "URGENT: Emergency PPE supplies 50 units",
                "status": "confirmed",
                "category": "Lab Supplies",
                "agreed_price": 9200.00,
                "currency": "INR",
                "created_at": "2026-05-05T16:42:00Z",
            },
            {
                "request_id": "req-g7h8i9j0",
                "raw_input_text": "Print supplies for Q2 marketing campaigns",
                "status": "discovering",
                "category": "Marketing",
                "agreed_price": None,
                "currency": "INR",
                "created_at": "2026-05-18T09:05:00Z",
            },
            {
                "request_id": "req-h8i9j0k1",
                "raw_input_text": "50 reams A4 printer paper for IT department",
                "status": "confirmed",
                "category": "Office Supplies",
                "agreed_price": 8250.00,
                "currency": "INR",
                "created_at": "2026-05-01T10:00:00Z",
            },
            {
                "request_id": "req-i9j0k1l2",
                "raw_input_text": "Conference room supplies and presentation materials",
                "status": "pending_approval",
                "category": "Office Supplies",
                "agreed_price": None,
                "currency": "INR",
                "created_at": "2026-05-16T15:20:00Z",
            },
            {
                "request_id": "req-j0k1l2m3",
                "raw_input_text": "Lab notebook and research materials for R&D team",
                "status": "confirmed",
                "category": "Lab Supplies",
                "agreed_price": 15600.00,
                "currency": "INR",
                "created_at": "2026-04-28T11:00:00Z",
            },
        ],
        "period": period,
        "data_source": "mock",
    }
