-- 02_bpp.sql
-- Entity 7: BPP (Beckn Provider Platform)
-- Seller registered on the Beckn / ONDC network.
-- Defined early because SellerOffering and PurchaseOrder reference it.
-- Store: PostgreSQL 16

CREATE TABLE IF NOT EXISTS bpp (
    bpp_id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                    VARCHAR(255)    NOT NULL,
    network_id              VARCHAR(100)    NOT NULL,
    endpoint_url            VARCHAR(500)    NOT NULL,
    reliability_score       FLOAT           NOT NULL DEFAULT 0.5
                                            CHECK (reliability_score >= 0.0 AND reliability_score <= 1.0),
    on_time_delivery_rate   FLOAT           NOT NULL DEFAULT 0.5
                                            CHECK (on_time_delivery_rate >= 0.0 AND on_time_delivery_rate <= 1.0),
    registered_at           TIMESTAMP       NOT NULL DEFAULT NOW(),
    last_seen_at            TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE bpp IS
    'Sellers (Beckn Provider Platforms) registered on the Beckn/ONDC network.';
COMMENT ON COLUMN bpp.reliability_score IS
    'Historical reliability score [0.0–1.0] computed by Agent Memory.';
COMMENT ON COLUMN bpp.on_time_delivery_rate IS
    'Fraction of orders delivered on time [0.0–1.0].';
COMMENT ON COLUMN bpp.endpoint_url IS
    'URL of the /bpp/receiver/* endpoint.';
