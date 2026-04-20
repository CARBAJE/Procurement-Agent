-- 13_erp_sync_records.sql
-- Entity 13: ERPSyncRecord
-- Each synchronization operation with SAP S/4HANA (OData) or Oracle ERP Cloud (REST).
-- budget_check is a blocking prerequisite before Beckn /confirm.
-- Triggered by Kafka consumer on the procurement.confirm topic.
-- Store: PostgreSQL 16
-- FK: purchase_orders(po_id)

CREATE TABLE IF NOT EXISTS erp_sync_records (
    sync_id             UUID                PRIMARY KEY DEFAULT uuid_generate_v4(),
    po_id               UUID                NOT NULL
                                            REFERENCES purchase_orders(po_id) ON DELETE RESTRICT,
    erp_system          erp_system_type     NOT NULL,
    sync_type           erp_sync_type       NOT NULL,
    status              erp_sync_status     NOT NULL DEFAULT 'pending',
    erp_reference_id    VARCHAR(255),
    budget_available    BOOLEAN,
    synced_at           TIMESTAMP           NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_budget_check_field CHECK (
        sync_type <> 'budget_check' OR budget_available IS NOT NULL
    )
);

COMMENT ON TABLE erp_sync_records IS
    'ERP sync record. budget_check is a blocking step; order blocked if budget_available=FALSE.';
COMMENT ON COLUMN erp_sync_records.budget_available IS
    'Only populated for sync_type=budget_check. TRUE = sufficient budget exists.';
COMMENT ON COLUMN erp_sync_records.erp_reference_id IS
    'Object ID in ERP, e.g. SAP PO number. NULL until ERP creates the object.';
