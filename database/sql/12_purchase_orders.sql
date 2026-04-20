-- 12_purchase_orders.sql
-- Entity 12: PurchaseOrder
-- Confirmed PO created only when ApprovalDecision.status IN ('approved','auto_approved')
-- and after ERP confirms budget availability.
-- Fires the Kafka event that activates the downstream ERP pipeline.
-- Store: PostgreSQL 16 · Protocol: Beckn /confirm
-- FK: approval_decisions(approval_id) — 1:1 (UNIQUE), bpp(bpp_id)

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id               UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    approval_id         UUID            NOT NULL UNIQUE
                                        REFERENCES approval_decisions(approval_id) ON DELETE RESTRICT,
    bpp_id              UUID            NOT NULL
                                        REFERENCES bpp(bpp_id) ON DELETE RESTRICT,
    item_id             VARCHAR(255)    NOT NULL,
    quantity            INTEGER         NOT NULL CHECK (quantity > 0),
    unit                VARCHAR(50)     NOT NULL,
    agreed_price        DECIMAL(15,2)   NOT NULL CHECK (agreed_price > 0),
    currency            CHAR(3)         NOT NULL,
    delivery_terms      TEXT            NOT NULL,
    beckn_confirm_ref   VARCHAR(255)    NOT NULL UNIQUE,
    erp_po_ref          VARCHAR(255)    UNIQUE,
    status              po_status_type  NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE purchase_orders IS
    'Confirmed PO; created after approval + ERP budget validation. Triggers downstream Kafka pipeline.';
COMMENT ON COLUMN purchase_orders.beckn_confirm_ref IS
    'Beckn protocol reference returned by the /confirm endpoint.';
COMMENT ON COLUMN purchase_orders.erp_po_ref IS
    'PO number assigned by SAP S/4HANA or Oracle ERP Cloud post-sync. NULL until ERP sync completes.';
