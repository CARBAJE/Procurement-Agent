-- 08_seller_offerings.sql
-- Entity 8: SellerOffering
-- Normalized offering received from a BPP after GET /discover.
-- Catalog Normalizer maps 5+ BPP JSON formats to this canonical schema.
-- Store: PostgreSQL 16
-- FK: discovery_queries(query_id), bpp(bpp_id)

CREATE TABLE IF NOT EXISTS seller_offerings (
    offering_id         UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id            UUID            NOT NULL
                                        REFERENCES discovery_queries(query_id) ON DELETE RESTRICT,
    bpp_id              UUID            NOT NULL
                                        REFERENCES bpp(bpp_id) ON DELETE RESTRICT,
    item_id             VARCHAR(255)    NOT NULL,
    price               DECIMAL(15,2)   NOT NULL CHECK (price > 0),
    currency            CHAR(3)         NOT NULL,
    delivery_eta_hours  INTEGER         NOT NULL CHECK (delivery_eta_hours > 0),
    quality_rating      FLOAT           CHECK (quality_rating >= 0.0 AND quality_rating <= 5.0),
    certifications      JSONB           NOT NULL DEFAULT '[]',
    inventory_count     INTEGER         CHECK (inventory_count >= 0),
    format_variant      INTEGER         NOT NULL DEFAULT 1
                                        CHECK (format_variant >= 1 AND format_variant <= 5),
    is_normalized       BOOLEAN         NOT NULL DEFAULT FALSE,
    received_at         TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE seller_offerings IS
    'Normalized BPP offering post GET /discover. Always in canonical schema regardless of source format.';
COMMENT ON COLUMN seller_offerings.format_variant IS
    'Original BPP format (1–5) before normalization, retained for traceability.';
COMMENT ON COLUMN seller_offerings.is_normalized IS
    'TRUE once the Catalog Normalizer has processed this record.';
