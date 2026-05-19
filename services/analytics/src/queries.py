"""Live PostgreSQL analytics queries.

All functions accept an asyncpg pool and a validated period string
("30d" | "90d" | "180d"). Returns None when the DB is empty so the
caller can fall back to mock data.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Pre-agent baseline cycle times per category (procurement team benchmarks).
_BASELINE_HOURS: dict[str, float] = {
    "Office Supplies": 72.0,
    "IT Equipment": 168.0,
    "Lab Supplies": 96.0,
    "Furniture": 120.0,
    "Marketing": 48.0,
}
_DEFAULT_BASELINE = 72.0


async def fetch_analytics(pool: Any, period: str) -> dict | None:
    """Return live KPIs from PostgreSQL.

    Returns None when the database contains no procurement data,
    signalling the caller to fall back to mock data.
    """
    period_days = {"30d": 30, "90d": 90, "180d": 180}[period]

    async with pool.acquire() as conn:

        # ── Spend & savings ───────────────────────────────────────────────────
        spend_row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(po.agreed_price * po.quantity), 0)::float        AS total_spend,
                COALESCE(SUM((no.initial_price - no.final_price) * po.quantity),
                         0)::float                                              AS total_savings
            FROM purchase_orders po
            JOIN approval_decisions   ad ON po.approval_id    = ad.approval_id
            JOIN negotiation_outcomes no ON ad.negotiation_id = no.negotiation_id
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
            """,
            period_days,
        )
        total_spend   = float(spend_row["total_spend"])
        total_savings = float(spend_row["total_savings"])

        # ── Live request counts (full table — not period-filtered) ────────────
        count_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE status IN ('parsing','discovering','scoring','negotiating')
                )::int AS active_requests,
                COUNT(*) FILTER (WHERE status = 'pending_approval')::int AS pending_approval,
                COUNT(*) FILTER (
                    WHERE status = 'confirmed'
                      AND date_trunc('month', created_at) = date_trunc('month', NOW())
                )::int AS completed_this_month
            FROM procurement_requests
            """,
        )
        active_requests      = int(count_row["active_requests"])
        pending_approval     = int(count_row["pending_approval"])
        completed_this_month = int(count_row["completed_this_month"])

        # ── Average cycle time for confirmed requests in the period ───────────
        cycle_row = await conn.fetchrow(
            """
            SELECT COALESCE(
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600), 0
            )::float AS avg_hours
            FROM procurement_requests
            WHERE status     = 'confirmed'
              AND created_at >= NOW() - ($1 * INTERVAL '1 day')
            """,
            period_days,
        )
        avg_cycle_time_hours = round(float(cycle_row["avg_hours"]), 1)

        # ── Distinct active suppliers ─────────────────────────────────────────
        sup_count_row = await conn.fetchrow(
            """
            SELECT COUNT(DISTINCT po.bpp_id)::int AS active_suppliers
            FROM purchase_orders po
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
            """,
            period_days,
        )
        active_suppliers = int(sup_count_row["active_suppliers"])

        # ── Weekly spend & savings time series ────────────────────────────────
        spend_rows = await conn.fetch(
            """
            SELECT
                date_trunc('week', po.created_at)::date                   AS week_start,
                SUM(po.agreed_price * po.quantity)::float                 AS spend,
                COALESCE(SUM((no.initial_price - no.final_price)
                             * po.quantity), 0)::float                    AS savings
            FROM purchase_orders po
            JOIN approval_decisions   ad ON po.approval_id    = ad.approval_id
            JOIN negotiation_outcomes no ON ad.negotiation_id = no.negotiation_id
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
            GROUP BY week_start
            ORDER BY week_start
            """,
            period_days,
        )
        spend_over_time = [
            {
                "date":    r["week_start"].strftime("%b %d"),
                "spend":   float(r["spend"]),
                "savings": round(float(r["savings"]), 2),
            }
            for r in spend_rows
        ]

        # ── Cycle time per category ───────────────────────────────────────────
        ct_rows = await conn.fetch(
            """
            SELECT
                category,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600)::float AS after_hours
            FROM procurement_requests
            WHERE status     = 'confirmed'
              AND created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND category   IS NOT NULL
            GROUP BY category
            ORDER BY category
            """,
            period_days,
        )
        cycle_time_by_category = [
            {
                "category":    r["category"],
                "before_hours": _BASELINE_HOURS.get(r["category"], _DEFAULT_BASELINE),
                "after_hours":  round(float(r["after_hours"]), 1),
            }
            for r in ct_rows
        ]

        # ── Spend by category ─────────────────────────────────────────────────
        cat_rows = await conn.fetch(
            """
            SELECT
                pr.category,
                COALESCE(SUM(po.agreed_price * po.quantity), 0)::float AS spend
            FROM procurement_requests pr
            JOIN parsed_intents       pi   ON pi.request_id      = pr.request_id
            JOIN beckn_intents        bi   ON bi.intent_id       = pi.intent_id
            JOIN discovery_queries    dq   ON dq.beckn_intent_id = bi.beckn_intent_id
            JOIN seller_offerings     soff ON soff.query_id      = dq.query_id
            JOIN scored_offers        sc   ON sc.offering_id     = soff.offering_id
            JOIN negotiation_outcomes no   ON no.score_id        = sc.score_id
            JOIN approval_decisions   ad   ON ad.negotiation_id  = no.negotiation_id
            JOIN purchase_orders      po   ON po.approval_id     = ad.approval_id
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
              AND pr.category    IS NOT NULL
            GROUP BY pr.category
            ORDER BY spend DESC
            """,
            period_days,
        )
        spend_by_category = [
            {"category": r["category"], "spend": float(r["spend"])}
            for r in cat_rows
        ]

        # ── Negotiation savings by category ───────────────────────────────────
        neg_rows = await conn.fetch(
            """
            SELECT
                pr.category,
                ROUND(
                    AVG((no.initial_price - no.final_price)
                        / NULLIF(no.initial_price, 0) * 100
                    )::numeric, 1
                )::float AS avg_discount_percent,
                COALESCE(SUM((no.initial_price - no.final_price) * po.quantity),
                         0)::float AS total_savings
            FROM procurement_requests pr
            JOIN parsed_intents       pi   ON pi.request_id      = pr.request_id
            JOIN beckn_intents        bi   ON bi.intent_id       = pi.intent_id
            JOIN discovery_queries    dq   ON dq.beckn_intent_id = bi.beckn_intent_id
            JOIN seller_offerings     soff ON soff.query_id      = dq.query_id
            JOIN scored_offers        sc   ON sc.offering_id     = soff.offering_id
            JOIN negotiation_outcomes no   ON no.score_id        = sc.score_id
            JOIN approval_decisions   ad   ON ad.negotiation_id  = no.negotiation_id
            JOIN purchase_orders      po   ON po.approval_id     = ad.approval_id
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
              AND pr.category    IS NOT NULL
            GROUP BY pr.category
            ORDER BY avg_discount_percent DESC
            """,
            period_days,
        )
        negotiation_savings = [
            {
                "category":             r["category"],
                "avg_discount_percent": float(r["avg_discount_percent"]),
                "total_savings":        float(r["total_savings"]),
            }
            for r in neg_rows
        ]

        # ── Request volume (weekly) ───────────────────────────────────────────
        vol_rows = await conn.fetch(
            """
            SELECT
                date_trunc('week', created_at)::date AS week_start,
                COUNT(*)::int                         AS count
            FROM procurement_requests
            WHERE created_at >= NOW() - ($1 * INTERVAL '1 day')
            GROUP BY week_start
            ORDER BY week_start
            """,
            period_days,
        )
        request_volume = [
            {
                "date":  r["week_start"].strftime("%b %d"),
                "count": int(r["count"]),
            }
            for r in vol_rows
        ]

        # ── Request status funnel ─────────────────────────────────────────────
        funnel_rows = await conn.fetch(
            """
            SELECT
                status::text,
                COUNT(*)::int AS count
            FROM procurement_requests
            WHERE created_at >= NOW() - ($1 * INTERVAL '1 day')
            GROUP BY status
            ORDER BY CASE status::text
                WHEN 'parsing'          THEN 1
                WHEN 'discovering'      THEN 2
                WHEN 'scoring'          THEN 3
                WHEN 'negotiating'      THEN 4
                WHEN 'pending_approval' THEN 5
                WHEN 'confirmed'        THEN 6
                WHEN 'cancelled'        THEN 7
                ELSE 8
            END
            """,
            period_days,
        )
        status_funnel = [
            {"status": r["status"], "count": int(r["count"])}
            for r in funnel_rows
        ]

        # ── Agent acceptance rate (weekly) ────────────────────────────────────
        acc_rows = await conn.fetch(
            """
            SELECT
                date_trunc('week', ad.decided_at)::date AS week_start,
                COUNT(*)::int                            AS total,
                COUNT(*) FILTER (
                    WHERE ad.status IN ('approved', 'auto_approved')
                      AND sc.user_overridden = FALSE
                )::int                                   AS accepted_count,
                COUNT(*) FILTER (
                    WHERE sc.user_overridden = TRUE
                )::int                                   AS overridden_count,
                ROUND(
                    COUNT(*) FILTER (
                        WHERE ad.status IN ('approved', 'auto_approved')
                          AND sc.user_overridden = FALSE
                    ) * 100.0 / NULLIF(COUNT(*), 0),
                    1
                )::float                                 AS accepted_pct
            FROM approval_decisions ad
            JOIN negotiation_outcomes no ON ad.negotiation_id = no.negotiation_id
            JOIN scored_offers        sc ON no.score_id       = sc.score_id
            WHERE ad.decided_at >= NOW() - ($1 * INTERVAL '1 day')
            GROUP BY week_start
            ORDER BY week_start
            """,
            period_days,
        )
        acceptance_rate = [
            {
                "date":             r["week_start"].strftime("%b %d"),
                "accepted_pct":     float(r["accepted_pct"]) if r["accepted_pct"] is not None else 0.0,
                "total":            int(r["total"]),
                "overridden_count": int(r["overridden_count"]),
            }
            for r in acc_rows
        ]

        # ── Supplier performance metrics ──────────────────────────────────────
        sup_rows = await conn.fetch(
            """
            SELECT
                b.name                                                          AS provider_name,
                soff.bpp_id::text                                               AS bpp_id,
                COUNT(DISTINCT po.po_id)::int                                   AS total_orders,
                ROUND(COALESCE(AVG(sc.quality_score),    0)::numeric, 1)::float AS quality_score,
                ROUND(COALESCE(AVG(sc.delivery_score),   0)::numeric, 1)::float AS delivery_score,
                ROUND(COALESCE(AVG(sc.price_score),      0)::numeric, 1)::float AS price_competitiveness,
                ROUND(COALESCE(AVG(sc.compliance_score), 0)::numeric, 1)::float AS compliance_score
            FROM purchase_orders po
            JOIN approval_decisions   ad   ON po.approval_id    = ad.approval_id
            JOIN negotiation_outcomes no   ON ad.negotiation_id = no.negotiation_id
            JOIN scored_offers        sc   ON no.score_id       = sc.score_id
            JOIN seller_offerings     soff ON sc.offering_id    = soff.offering_id
            JOIN bpp                  b    ON soff.bpp_id       = b.bpp_id
            WHERE po.created_at >= NOW() - ($1 * INTERVAL '1 day')
              AND po.status      != 'cancelled'
            GROUP BY soff.bpp_id, b.name
            ORDER BY total_orders DESC
            LIMIT 6
            """,
            period_days,
        )
        supplier_metrics = [
            {
                "bpp_id":                r["bpp_id"],
                "provider_name":         r["provider_name"],
                "quality_score":         float(r["quality_score"]),
                "delivery_score":        float(r["delivery_score"]),
                "price_competitiveness": float(r["price_competitiveness"]),
                "compliance_score":      float(r["compliance_score"]),
                "total_orders":          r["total_orders"],
            }
            for r in sup_rows
        ]

        # ── Recent requests with PO price when available ──────────────────────
        req_rows = await conn.fetch(
            """
            SELECT
                pr.request_id::text,
                pr.raw_input_text,
                pr.status::text  AS status,
                pr.category,
                pr.created_at,
                pod.agreed_price,
                pod.currency,
                pod.user_overridden
            FROM procurement_requests pr
            LEFT JOIN (
                SELECT
                    pi2.request_id,
                    po2.agreed_price::float AS agreed_price,
                    po2.currency,
                    sc2.user_overridden
                FROM purchase_orders  po2
                JOIN approval_decisions   ad2  ON po2.approval_id     = ad2.approval_id
                JOIN negotiation_outcomes no2  ON ad2.negotiation_id  = no2.negotiation_id
                JOIN scored_offers        sc2  ON no2.score_id        = sc2.score_id
                JOIN seller_offerings     sof2 ON sc2.offering_id     = sof2.offering_id
                JOIN discovery_queries    dq2  ON sof2.query_id       = dq2.query_id
                JOIN beckn_intents        bi2  ON dq2.beckn_intent_id = bi2.beckn_intent_id
                JOIN parsed_intents       pi2  ON bi2.intent_id       = pi2.intent_id
                WHERE po2.status != 'cancelled'
            ) pod ON pod.request_id = pr.request_id
            WHERE pr.created_at >= NOW() - ($1 * INTERVAL '1 day')
            ORDER BY pr.created_at DESC
            LIMIT 10
            """,
            period_days,
        )
        recent_requests = [
            {
                "request_id":    r["request_id"],
                "raw_input_text": r["raw_input_text"],
                "status":        r["status"],
                "category":      r["category"],
                "agreed_price":   float(r["agreed_price"]) if r["agreed_price"] is not None else None,
                "currency":       r["currency"] if r["currency"] else "INR",
                "created_at":     r["created_at"].isoformat() + "Z",
                "user_overridden": bool(r["user_overridden"]) if r["user_overridden"] is not None else None,
            }
            for r in req_rows
        ]

    if not recent_requests and total_spend == 0.0:
        logger.info("DB returned no procurement data — signalling mock fallback")
        return None

    savings_pct = round(total_savings / total_spend * 100, 1) if total_spend else 0.0

    return {
        "kpis": {
            "total_spend":               round(total_spend, 2),
            "total_savings":             round(total_savings, 2),
            "savings_percent":           savings_pct,
            "active_requests":           active_requests,
            "completed_this_month":      completed_this_month,
            "pending_approval":          pending_approval,
            "avg_cycle_time_hours":      avg_cycle_time_hours,
            "baseline_cycle_time_hours": 72.0,
            "active_suppliers":          active_suppliers,
        },
        "spend_over_time":        spend_over_time,
        "cycle_time_by_category": cycle_time_by_category,
        "spend_by_category":      spend_by_category,
        "negotiation_savings":    negotiation_savings,
        "request_volume":         request_volume,
        "status_funnel":          status_funnel,
        "acceptance_rate":        acceptance_rate,
        "supplier_metrics":       supplier_metrics,
        "recent_requests":        recent_requests,
        "period":                 period,
        "data_source":            "live",
    }
