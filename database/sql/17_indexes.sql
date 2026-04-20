-- 17_indexes.sql
-- All PostgreSQL indexes for the Procurement Agent schema.
-- Sourced from the data dictionary recommendations plus additional operational indexes.

-- ── procurement_requests ───────────────────────────────────────────────────────

-- Fast lookup of all requests by a given user, newest first
CREATE INDEX IF NOT EXISTS idx_procurement_requests_requester
    ON procurement_requests(requester_id, created_at DESC);

-- Filter active requests only (avoids touching completed/cancelled rows)
CREATE INDEX IF NOT EXISTS idx_procurement_requests_status
    ON procurement_requests(status)
    WHERE status NOT IN ('confirmed', 'cancelled');

-- ── audit_trail_events ────────────────────────────────────────────────────────

-- Full audit chain for a request (primary traceability query)
CREATE INDEX IF NOT EXISTS idx_audit_events_request
    ON audit_trail_events(request_id, event_timestamp)
    WHERE request_id IS NOT NULL;

-- Filter events by type and time window (SOX reporting queries)
CREATE INDEX IF NOT EXISTS idx_audit_events_type
    ON audit_trail_events(event_type, event_timestamp);

-- Audit events linked to a specific PO
CREATE INDEX IF NOT EXISTS idx_audit_events_po
    ON audit_trail_events(po_id, event_timestamp)
    WHERE po_id IS NOT NULL;

-- Batch job: find events not yet pushed to Splunk
CREATE INDEX IF NOT EXISTS idx_audit_events_splunk_pending
    ON audit_trail_events(splunk_indexed, event_timestamp)
    WHERE splunk_indexed = FALSE;

-- ── seller_offerings ──────────────────────────────────────────────────────────

-- All offerings returned by a discovery query
CREATE INDEX IF NOT EXISTS idx_seller_offerings_query
    ON seller_offerings(query_id);

-- All offerings from a given BPP
CREATE INDEX IF NOT EXISTS idx_seller_offerings_bpp
    ON seller_offerings(bpp_id);

-- ── scored_offers ─────────────────────────────────────────────────────────────

-- Calibration job: count user overrides in rolling 30-day window
CREATE INDEX IF NOT EXISTS idx_scored_offers_overridden
    ON scored_offers(user_overridden, scored_at)
    WHERE user_overridden = TRUE;

-- ── purchase_orders ───────────────────────────────────────────────────────────

-- Active orders per BPP (excludes delivered/cancelled)
CREATE INDEX IF NOT EXISTS idx_purchase_orders_bpp
    ON purchase_orders(bpp_id, status)
    WHERE status NOT IN ('delivered', 'cancelled');

-- Status filter (operations dashboard)
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status
    ON purchase_orders(status, created_at DESC);

-- ── model_governance_records ──────────────────────────────────────────────────

-- Latest evaluation per model name
CREATE INDEX IF NOT EXISTS idx_model_governance_name
    ON model_governance_records(model_name, evaluation_date DESC);

-- Active / under-review models only
CREATE INDEX IF NOT EXISTS idx_model_governance_status
    ON model_governance_records(status)
    WHERE status <> 'deprecated';

-- ── bpp ───────────────────────────────────────────────────────────────────────

-- Lookup by Beckn network ID
CREATE INDEX IF NOT EXISTS idx_bpp_network
    ON bpp(network_id);

-- ── erp_sync_records ─────────────────────────────────────────────────────────

-- Sync history for a given PO grouped by operation type
CREATE INDEX IF NOT EXISTS idx_erp_sync_po
    ON erp_sync_records(po_id, sync_type);

-- Retry queue: find pending ERP sync records
CREATE INDEX IF NOT EXISTS idx_erp_sync_pending
    ON erp_sync_records(status, synced_at)
    WHERE status = 'pending';

-- ── discovery_queries ─────────────────────────────────────────────────────────

-- All queries triggered by a given beckn_intent
CREATE INDEX IF NOT EXISTS idx_discovery_queries_intent
    ON discovery_queries(beckn_intent_id, queried_at DESC);

-- ── approval_decisions ────────────────────────────────────────────────────────

-- Dashboard: all pending / escalated decisions
CREATE INDEX IF NOT EXISTS idx_approval_decisions_status
    ON approval_decisions(status)
    WHERE status IN ('pending', 'escalated');

-- Approver inbox: open decisions assigned to a user
CREATE INDEX IF NOT EXISTS idx_approval_decisions_approver
    ON approval_decisions(approver_id, status)
    WHERE approver_id IS NOT NULL;

-- ── agent_memory_vectors ──────────────────────────────────────────────────────

-- Filter vectors by entity type (RAG retrieval routing)
CREATE INDEX IF NOT EXISTS idx_agent_memory_entity_type
    ON agent_memory_vectors(entity_type);

-- Vectors originating from a specific request
CREATE INDEX IF NOT EXISTS idx_agent_memory_request
    ON agent_memory_vectors(source_request_id)
    WHERE source_request_id IS NOT NULL;
