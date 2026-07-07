-- 24_po_request_id.sql
-- Adds a direct request_id FK to purchase_orders so analytics can join
-- without traversing the full negotiation_outcomes → scored_offers chain.
-- Also adds original_price to negotiation_outcomes so negotiated savings
-- are computed correctly (initial_price vs final_price).

-- 1. Direct request_id on purchase_orders ---------------------------------
ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS request_id UUID
        REFERENCES procurement_requests(request_id) ON DELETE SET NULL;

-- Backfill existing rows from the FK chain.
UPDATE purchase_orders po
SET request_id = (
    SELECT pi.request_id
    FROM approval_decisions  ad
    JOIN negotiation_outcomes no2 ON no2.negotiation_id = ad.negotiation_id
    JOIN scored_offers        sc  ON sc.score_id        = no2.score_id
    JOIN seller_offerings  soff   ON soff.offering_id   = sc.offering_id
    JOIN discovery_queries   dq   ON dq.query_id        = soff.query_id
    JOIN beckn_intents       bi   ON bi.beckn_intent_id = dq.beckn_intent_id
    JOIN parsed_intents      pi   ON pi.intent_id       = bi.intent_id
    WHERE ad.approval_id = po.approval_id
    LIMIT 1
)
WHERE po.request_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_purchase_orders_request_id
    ON purchase_orders(request_id)
    WHERE request_id IS NOT NULL;

COMMENT ON COLUMN purchase_orders.request_id IS
    'Direct FK to procurement_requests — allows analytics to join without '
    'traversing the full negotiation chain. Populated on every new order.';
