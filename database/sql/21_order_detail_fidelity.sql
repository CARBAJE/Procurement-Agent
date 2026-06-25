-- 21_order_detail_fidelity.sql
-- Phase 3 — Backend-backed order detail (view any past order).
--
-- Adds the two fields the order-detail page renders but that were never
-- persisted, so a committed order can be reconstructed full-fidelity from the
-- DB (not just from the ephemeral browser session). Purely additive — no new
-- table, no destructive change. Idempotent.
--
-- Depends on 08_seller_offerings.sql and 12_purchase_orders.sql (tables must
-- already exist). Runs after them by lexicographic order.

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. seller_offerings.item_name — the seller's human-readable product label.
--    Previously only beckn_intents.item (the *requested* term) was stored; the
--    BPP's catalog item name was dropped. Populated at /normalize/discovery.
-- ──────────────────────────────────────────────────────────────────────────────

ALTER TABLE seller_offerings
    ADD COLUMN IF NOT EXISTS item_name VARCHAR(255);

-- ──────────────────────────────────────────────────────────────────────────────
-- 2. purchase_orders.fulfillment_eta — absolute delivery ETA computed at
--    /confirm. Previously only seller_offerings.delivery_eta_hours (relative)
--    existed. Populated at /normalize/order.
-- ──────────────────────────────────────────────────────────────────────────────

ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS fulfillment_eta TIMESTAMPTZ;
