#!/usr/bin/env python3
"""
Database integration tests for Procurement Agent Beckn Protocol.

Verifies:
  - Extensions, ENUM types, tables, and indexes exist
  - All FK, UNIQUE, and CHECK constraints are enforced
  - A complete end-to-end procurement workflow can be inserted and queried

Run:
    pytest test_database.py -v
    pytest test_database.py -v --tb=short   # compact tracebacks

Environment variables:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD  (same as setup_database.py)

Requirements:
    pip install pytest psycopg2-binary
"""

import os
import uuid
from typing import Generator

import pytest

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.errors
except ImportError:
    pytest.exit(
        "psycopg2 not installed. Run: pip install psycopg2-binary", returncode=1
    )


# ──────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _conn_params() -> dict:
    return {
        "host":     os.getenv("DB_HOST",     "localhost"),
        "port":     int(os.getenv("DB_PORT", "5432")),
        "dbname":   os.getenv("DB_NAME",     "procurement_agent"),
        "user":     os.getenv("DB_USER",     "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Session fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def conn() -> Generator:
    """Single DB connection reused across the entire test session."""
    c = psycopg2.connect(**_conn_params())
    c.autocommit = False
    yield c
    c.close()


@pytest.fixture(scope="session")
def cur(conn) -> Generator:
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield c
    c.close()


@pytest.fixture(scope="session")
def workflow_ids(conn, cur) -> Generator:
    """
    Creates a complete end-to-end procurement workflow in the DB,
    yields the dict of IDs for assertion tests, then deletes all test data.
    """
    ids: dict = {}

    # ── Users ─────────────────────────────────────────────────────────────────
    req_uid, apr_uid = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO users
            (user_id, email, name, role, department, approval_threshold,
             keycloak_id, idp_provider)
        VALUES
            (%s, %s, 'Test Requester', 'requester', 'Procurement', 0.00,    %s, 'keycloak'),
            (%s, %s, 'Test Approver',  'approver',  'Finance',     50000.00, %s, 'keycloak')
        """,
        (
            req_uid, f"test_requester_{req_uid}@test.local", f"kc-{req_uid}",
            apr_uid, f"test_approver_{apr_uid}@test.local",  f"kc-{apr_uid}",
        ),
    )
    ids["requester_id"] = req_uid
    ids["approver_id"]  = apr_uid

    # ── BPP ───────────────────────────────────────────────────────────────────
    bpp_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO bpp (bpp_id, name, network_id, endpoint_url,
                         reliability_score, on_time_delivery_rate,
                         registered_at, last_seen_at)
        VALUES (%s, 'Test Supplier Co.', %s,
                'https://test.bpp.local/receiver',
                0.88, 0.92, NOW(), NOW())
        """,
        (bpp_id, f"test-bpp-{bpp_id}.ondc"),
    )
    ids["bpp_id"] = bpp_id

    # ── ProcurementRequest ────────────────────────────────────────────────────
    pr_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO procurement_requests
            (request_id, requester_id, raw_input_text, channel, status)
        VALUES (%s, %s, 'TEST: Need 500 reams of A4 paper by Friday', 'web', 'draft')
        """,
        (pr_id, req_uid),
    )
    ids["request_id"] = pr_id

    # ── ParsedIntent ──────────────────────────────────────────────────────────
    pi_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO parsed_intents
            (intent_id, request_id, intent_class, confidence_score, model_version)
        VALUES (%s, %s, 'procurement', 0.98, 'test-gpt-4o-2024-11-20')
        """,
        (pi_id, pr_id),
    )
    ids["intent_id"] = pi_id

    # ── BecknIntent ───────────────────────────────────────────────────────────
    bi_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO beckn_intents
            (beckn_intent_id, intent_id, item, descriptions, quantity,
             unit, location_coordinates, delivery_timeline_hours,
             budget_min, budget_max, currency, compliance_requirements)
        VALUES (%s, %s, 'TEST-A4-paper',
                '["80gsm", "white", "500 sheets/ream"]',
                500, 'reams', '12.9716,77.5946', 72,
                800.00, 1200.00, 'INR', '[]')
        """,
        (bi_id, pi_id),
    )
    ids["beckn_intent_id"] = bi_id

    # ── DiscoveryQuery ────────────────────────────────────────────────────────
    dq_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO discovery_queries
            (query_id, beckn_intent_id, network_id, cache_hit, results_count)
        VALUES (%s, %s, 'test-ondc-prod-01', FALSE, 3)
        """,
        (dq_id, bi_id),
    )
    ids["query_id"] = dq_id

    # ── CatalogCache ──────────────────────────────────────────────────────────
    cache_key = f"test_a4paper_12.9716_77.5946_{uuid.uuid4().hex[:8]}"
    cur.execute(
        """
        INSERT INTO catalog_cache (cache_key, query_id, cached_offerings)
        VALUES (%s, %s, '[{"item":"A4 paper","price":950.00}]')
        """,
        (cache_key, dq_id),
    )
    ids["cache_key"] = cache_key

    # ── SellerOffering ────────────────────────────────────────────────────────
    so_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO seller_offerings
            (offering_id, query_id, bpp_id, item_id, price, currency,
             delivery_eta_hours, quality_rating, certifications,
             inventory_count, format_variant, is_normalized)
        VALUES (%s, %s, %s, 'TEST-ITEM-A4-001', 950.00, 'INR',
                48, 4.2, '["ISO 9001"]', 10000, 2, TRUE)
        """,
        (so_id, dq_id, bpp_id),
    )
    ids["offering_id"] = so_id

    # ── ScoredOffer ───────────────────────────────────────────────────────────
    sc_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO scored_offers
            (score_id, offering_id, rank, total_score,
             price_score, delivery_score, quality_score, compliance_score,
             tco_value, explanation_text, model_version)
        VALUES (%s, %s, 1, 87.5, 85.0, 90.0, 88.0, 87.0,
                475000.00,
                'Test Supplier recommended: best TCO with ISO 9001 compliance.',
                'test-gpt-4o-2024-11-20')
        """,
        (sc_id, so_id),
    )
    ids["score_id"] = sc_id

    # ── NegotiationOutcome ────────────────────────────────────────────────────
    neg_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO negotiation_outcomes
            (negotiation_id, score_id, strategy_applied,
             initial_price, counter_offer_price, final_price,
             discount_percent, acceptance_status)
        VALUES (%s, %s, 'aggressive',
                950.00, 870.00, 902.50, 5.0, 'accepted')
        """,
        (neg_id, sc_id),
    )
    ids["negotiation_id"] = neg_id

    # ── ApprovalDecision ──────────────────────────────────────────────────────
    ap_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO approval_decisions
            (approval_id, negotiation_id, requester_id, approver_id,
             approval_level, amount_total, status, notification_channel)
        VALUES (%s, %s, %s, %s, 'manager', 45125.00, 'approved', 'slack')
        """,
        (ap_id, neg_id, req_uid, apr_uid),
    )
    ids["approval_id"] = ap_id

    # ── PurchaseOrder ─────────────────────────────────────────────────────────
    po_id      = str(uuid.uuid4())
    beckn_ref  = f"TEST-BECKN-{uuid.uuid4().hex[:12].upper()}"
    cur.execute(
        """
        INSERT INTO purchase_orders
            (po_id, approval_id, bpp_id, item_id, quantity, unit,
             agreed_price, currency, delivery_terms, beckn_confirm_ref, status)
        VALUES (%s, %s, %s, 'TEST-ITEM-A4-001', 500, 'reams',
                902.50, 'INR', 'FOB Mumbai — 48h delivery guaranteed',
                %s, 'confirmed')
        """,
        (po_id, ap_id, bpp_id, beckn_ref),
    )
    ids["po_id"]          = po_id
    ids["beckn_confirm_ref"] = beckn_ref

    # ── ERPSyncRecord ─────────────────────────────────────────────────────────
    sync_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO erp_sync_records
            (sync_id, po_id, erp_system, sync_type, status,
             erp_reference_id, budget_available)
        VALUES (%s, %s, 'sap_s4hana', 'budget_check', 'success',
                'TEST-SAP-4500000001', TRUE)
        """,
        (sync_id, po_id),
    )
    ids["sync_id"] = sync_id

    # ── AuditTrailEvent ───────────────────────────────────────────────────────
    ev_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO audit_trail_events
            (event_id, request_id, po_id, actor_id, event_type,
             agent_action, reasoning_payload, kafka_offset)
        VALUES (%s, %s, %s, %s, 'confirm',
                'TEST: Beckn /confirm executed successfully',
                '{"test": true, "step": "confirm", "beckn_ref": "TEST-123"}',
                100000001)
        """,
        (ev_id, pr_id, po_id, req_uid),
    )
    ids["event_id"] = ev_id

    # ── AgentMemoryVector ─────────────────────────────────────────────────────
    vec_id    = str(uuid.uuid4())
    embedding = "[" + ",".join(["0.001"] * 3072) + "]"
    cur.execute(
        """
        INSERT INTO agent_memory_vectors
            (vector_id, source_request_id, entity_type,
             embedding_vector, metadata, embedding_model)
        VALUES (%s, %s, 'transaction', %s::vector,
                '{"test": "true", "item": "A4 paper", "quantity": 500}',
                'text-embedding-3-large')
        """,
        (vec_id, pr_id, embedding),
    )
    ids["vector_id"] = vec_id

    # ── ModelGovernanceRecord ─────────────────────────────────────────────────
    gov_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO model_governance_records
            (record_id, model_name, model_version, provider,
             accuracy_score, override_rate, evaluation_date, status)
        VALUES (%s, 'intent_parsing', 'test-gpt-4o-2024-11-20', 'openai',
                0.97, 0.04, '2026-04-20', 'active')
        """,
        (gov_id,),
    )
    ids["gov_id"] = gov_id

    conn.commit()

    # ── yield IDs to all tests ────────────────────────────────────────────────
    yield ids

    # ── Teardown: delete in reverse FK order ─────────────────────────────────
    cur.execute("DELETE FROM model_governance_records WHERE record_id = %s",  (gov_id,))
    cur.execute("DELETE FROM agent_memory_vectors    WHERE vector_id  = %s",  (vec_id,))
    cur.execute("DELETE FROM audit_trail_events      WHERE event_id   = %s",  (ev_id,))
    cur.execute("DELETE FROM erp_sync_records        WHERE sync_id    = %s",  (sync_id,))
    cur.execute("DELETE FROM purchase_orders         WHERE po_id      = %s",  (po_id,))
    cur.execute("DELETE FROM approval_decisions      WHERE approval_id = %s", (ap_id,))
    cur.execute("DELETE FROM negotiation_outcomes    WHERE negotiation_id = %s", (neg_id,))
    cur.execute("DELETE FROM scored_offers           WHERE score_id   = %s",  (sc_id,))
    cur.execute("DELETE FROM seller_offerings        WHERE offering_id = %s", (so_id,))
    cur.execute("DELETE FROM catalog_cache           WHERE cache_key  = %s",  (cache_key,))
    cur.execute("DELETE FROM discovery_queries       WHERE query_id   = %s",  (dq_id,))
    cur.execute("DELETE FROM beckn_intents           WHERE beckn_intent_id = %s", (bi_id,))
    cur.execute("DELETE FROM parsed_intents          WHERE intent_id  = %s",  (pi_id,))
    cur.execute("DELETE FROM procurement_requests    WHERE request_id = %s",  (pr_id,))
    cur.execute("DELETE FROM bpp                     WHERE bpp_id     = %s",  (bpp_id,))
    cur.execute("DELETE FROM users WHERE user_id IN (%s, %s)", (req_uid, apr_uid))
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# 1. Basic connectivity
# ──────────────────────────────────────────────────────────────────────────────

class TestConnection:
    def test_can_connect(self, conn):
        assert conn.closed == 0

    def test_is_postgresql(self, cur, conn):
        cur.execute("SELECT version()")
        row = cur.fetchone()
        assert "PostgreSQL" in row["version"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Extensions
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_EXTENSIONS = ["uuid-ossp", "pgcrypto", "vector"]


class TestExtensions:
    @pytest.mark.parametrize("ext", REQUIRED_EXTENSIONS)
    def test_extension_installed(self, cur, conn, ext):
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = %s", (ext,))
        assert cur.fetchone() is not None, f"Extension '{ext}' not installed"


# ──────────────────────────────────────────────────────────────────────────────
# 3. ENUM types
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_ENUMS = [
    "user_role",
    "idp_provider_type",
    "channel_type",
    "procurement_status",
    "intent_class_type",
    "negotiation_strategy_type",
    "acceptance_status_type",
    "approval_level_type",
    "approval_status_type",
    "notification_channel_type",
    "po_status_type",
    "erp_system_type",
    "erp_sync_type",
    "erp_sync_status",
    "audit_event_type",
    "memory_entity_type",
    "embedding_model_type",
    "model_name_type",
    "ai_provider_type",
    "governance_status_type",
]


class TestEnumTypes:
    @pytest.mark.parametrize("enum_name", REQUIRED_ENUMS)
    def test_enum_exists(self, cur, conn, enum_name):
        cur.execute(
            """
            SELECT 1 FROM pg_type t
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public' AND t.typname = %s AND t.typtype = 'e'
            """,
            (enum_name,),
        )
        assert cur.fetchone() is not None, f"ENUM type '{enum_name}' not found"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tables
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_TABLES = [
    "users",
    "bpp",
    "procurement_requests",
    "parsed_intents",
    "beckn_intents",
    "discovery_queries",
    "catalog_cache",
    "seller_offerings",
    "scored_offers",
    "negotiation_outcomes",
    "approval_decisions",
    "purchase_orders",
    "erp_sync_records",
    "audit_trail_events",
    "agent_memory_vectors",
    "model_governance_records",
]


class TestTables:
    @pytest.mark.parametrize("table", REQUIRED_TABLES)
    def test_table_exists(self, cur, conn, table):
        cur.execute(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=%s",
            (table,),
        )
        assert cur.fetchone() is not None, f"Table '{table}' not found"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Indexes
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_INDEXES = [
    "idx_procurement_requests_requester",
    "idx_procurement_requests_status",
    "idx_audit_events_request",
    "idx_audit_events_type",
    "idx_audit_events_po",
    "idx_audit_events_splunk_pending",
    "idx_seller_offerings_query",
    "idx_seller_offerings_bpp",
    "idx_purchase_orders_bpp",
    "idx_purchase_orders_status",
    "idx_model_governance_name",
    "idx_model_governance_status",
    "idx_bpp_network",
    "idx_erp_sync_po",
    "idx_erp_sync_pending",
    "idx_discovery_queries_intent",
    "idx_approval_decisions_status",
    "idx_approval_decisions_approver",
    "idx_agent_memory_entity_type",
    "idx_agent_memory_request",
    "idx_scored_offers_overridden",
]


class TestIndexes:
    @pytest.mark.parametrize("index_name", REQUIRED_INDEXES)
    def test_index_exists(self, cur, conn, index_name):
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=%s",
            (index_name,),
        )
        assert cur.fetchone() is not None, f"Index '{index_name}' not found"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Workflow data — rows were inserted by the fixture
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkflowRows:
    def test_user_requester_exists(self, cur, conn, workflow_ids):
        cur.execute("SELECT role FROM users WHERE user_id=%s",
                    (workflow_ids["requester_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["role"] == "requester"

    def test_user_approver_exists(self, cur, conn, workflow_ids):
        cur.execute("SELECT approval_threshold FROM users WHERE user_id=%s",
                    (workflow_ids["approver_id"],))
        row = cur.fetchone()
        assert row is not None
        assert float(row["approval_threshold"]) == pytest.approx(50000.00)

    def test_bpp_reliability_score(self, cur, conn, workflow_ids):
        cur.execute("SELECT reliability_score FROM bpp WHERE bpp_id=%s",
                    (workflow_ids["bpp_id"],))
        row = cur.fetchone()
        assert row is not None
        assert float(row["reliability_score"]) == pytest.approx(0.88)

    def test_procurement_request_exists(self, cur, conn, workflow_ids):
        cur.execute("SELECT status FROM procurement_requests WHERE request_id=%s",
                    (workflow_ids["request_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "draft"

    def test_parsed_intent_confidence(self, cur, conn, workflow_ids):
        cur.execute("SELECT confidence_score, intent_class FROM parsed_intents WHERE intent_id=%s",
                    (workflow_ids["intent_id"],))
        row = cur.fetchone()
        assert row is not None
        assert float(row["confidence_score"]) == pytest.approx(0.98)
        assert row["intent_class"] == "procurement"

    def test_beckn_intent_fields(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT item, quantity, unit, currency FROM beckn_intents WHERE beckn_intent_id=%s",
            (workflow_ids["beckn_intent_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["item"] == "TEST-A4-paper"
        assert row["quantity"] == 500
        assert row["unit"] == "reams"
        assert row["currency"] == "INR"

    def test_discovery_query_results_count(self, cur, conn, workflow_ids):
        cur.execute("SELECT results_count FROM discovery_queries WHERE query_id=%s",
                    (workflow_ids["query_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["results_count"] == 3

    def test_seller_offering_normalized(self, cur, conn, workflow_ids):
        cur.execute("SELECT is_normalized, price FROM seller_offerings WHERE offering_id=%s",
                    (workflow_ids["offering_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["is_normalized"] is True
        assert float(row["price"]) == pytest.approx(950.00)

    def test_scored_offer_rank_and_total(self, cur, conn, workflow_ids):
        cur.execute("SELECT rank, total_score FROM scored_offers WHERE score_id=%s",
                    (workflow_ids["score_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["rank"] == 1
        assert float(row["total_score"]) == pytest.approx(87.5)

    def test_negotiation_outcome_discount(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT discount_percent, acceptance_status FROM negotiation_outcomes WHERE negotiation_id=%s",
            (workflow_ids["negotiation_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert float(row["discount_percent"]) == pytest.approx(5.0)
        assert row["acceptance_status"] == "accepted"

    def test_approval_decision_approved(self, cur, conn, workflow_ids):
        cur.execute("SELECT status, approval_level FROM approval_decisions WHERE approval_id=%s",
                    (workflow_ids["approval_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "approved"
        assert row["approval_level"] == "manager"

    def test_purchase_order_confirmed(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT status, beckn_confirm_ref FROM purchase_orders WHERE po_id=%s",
            (workflow_ids["po_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "confirmed"
        assert row["beckn_confirm_ref"] == workflow_ids["beckn_confirm_ref"]

    def test_erp_sync_budget_available(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT sync_type, budget_available FROM erp_sync_records WHERE sync_id=%s",
            (workflow_ids["sync_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["sync_type"] == "budget_check"
        assert row["budget_available"] is True

    def test_audit_event_retention(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT retention_until, event_type FROM audit_trail_events WHERE event_id=%s",
            (workflow_ids["event_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["event_type"] == "confirm"
        # Retention must be approximately 7 years from now
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        delta_years = (row["retention_until"] - now).days / 365.0
        assert delta_years == pytest.approx(7.0, abs=0.1)

    def test_agent_memory_vector_inserted(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT entity_type, embedding_model FROM agent_memory_vectors WHERE vector_id=%s",
            (workflow_ids["vector_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["entity_type"] == "transaction"
        assert row["embedding_model"] == "text-embedding-3-large"

    def test_model_governance_active(self, cur, conn, workflow_ids):
        cur.execute(
            "SELECT status, accuracy_score FROM model_governance_records WHERE record_id=%s",
            (workflow_ids["gov_id"],),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "active"
        assert float(row["accuracy_score"]) == pytest.approx(0.97)


# ──────────────────────────────────────────────────────────────────────────────
# 7. Full end-to-end JOIN query
# ──────────────────────────────────────────────────────────────────────────────

class TestEndToEndQuery:
    def test_full_procurement_chain(self, cur, conn, workflow_ids):
        """Single JOIN across all 12 core PostgreSQL tables."""
        cur.execute(
            """
            SELECT
                pr.raw_input_text,
                pr.status                   AS request_status,
                pi2.intent_class,
                pi2.confidence_score,
                bi.item,
                bi.quantity,
                dq.network_id,
                dq.results_count,
                b.name                      AS seller_name,
                so.price                    AS list_price,
                sc.rank,
                sc.total_score,
                n.strategy_applied,
                n.discount_percent,
                n.final_price,
                ad.approval_level,
                ad.status                   AS approval_status,
                po.beckn_confirm_ref,
                po.status                   AS po_status,
                es.sync_type,
                es.budget_available
            FROM procurement_requests pr
            JOIN parsed_intents      pi2 ON pi2.request_id         = pr.request_id
            JOIN beckn_intents       bi  ON bi.intent_id            = pi2.intent_id
            JOIN discovery_queries   dq  ON dq.beckn_intent_id      = bi.beckn_intent_id
            JOIN seller_offerings    so  ON so.query_id             = dq.query_id
            JOIN bpp                 b   ON b.bpp_id                = so.bpp_id
            JOIN scored_offers       sc  ON sc.offering_id          = so.offering_id
            JOIN negotiation_outcomes n  ON n.score_id              = sc.score_id
            JOIN approval_decisions  ad  ON ad.negotiation_id       = n.negotiation_id
            JOIN purchase_orders     po  ON po.approval_id          = ad.approval_id
            JOIN erp_sync_records    es  ON es.po_id                = po.po_id
            WHERE pr.request_id = %s
            """,
            (workflow_ids["request_id"],),
        )
        row = cur.fetchone()
        assert row is not None, "Full-chain JOIN returned no rows"

        assert row["intent_class"]        == "procurement"
        assert float(row["confidence_score"]) == pytest.approx(0.98)
        assert row["item"]                == "TEST-A4-paper"
        assert row["quantity"]            == 500
        assert row["network_id"]          == "test-ondc-prod-01"
        assert row["rank"]                == 1
        assert row["strategy_applied"]    == "aggressive"
        assert float(row["discount_percent"]) == pytest.approx(5.0)
        assert row["approval_level"]      == "manager"
        assert row["approval_status"]     == "approved"
        assert row["po_status"]           == "confirmed"
        assert row["sync_type"]           == "budget_check"
        assert row["budget_available"]    is True


# ──────────────────────────────────────────────────────────────────────────────
# 8. Constraint enforcement
# ──────────────────────────────────────────────────────────────────────────────

class TestConstraints:
    # ── CHECK constraints ─────────────────────────────────────────────────────

    def test_bpp_reliability_score_above_1(self, cur, conn):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO bpp (bpp_id, name, network_id, endpoint_url,
                                    reliability_score, on_time_delivery_rate,
                                    registered_at, last_seen_at)
                   VALUES (%s,'Bad BPP','bad.net','https://bad.local',
                           1.5, 0.5, NOW(), NOW())""",
                (str(uuid.uuid4()),),
            )
            conn.commit()
        conn.rollback()

    def test_confidence_score_above_1(self, cur, conn, workflow_ids):
        pr_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO procurement_requests
                   (request_id, requester_id, raw_input_text, channel, status)
               VALUES (%s,%s,'TEST: dummy','web','draft')""",
            (pr_id, workflow_ids["requester_id"]),
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO parsed_intents
                       (intent_id, request_id, intent_class, confidence_score, model_version)
                   VALUES (%s,%s,'procurement',1.99,'test-bad')""",
                (str(uuid.uuid4()), pr_id),
            )
            conn.commit()
        conn.rollback()
        cur.execute("DELETE FROM procurement_requests WHERE request_id=%s", (pr_id,))
        conn.commit()

    def test_negotiation_discount_above_20(self, cur, conn, workflow_ids):
        """Insert an independent chain just to test the 20% discount hard limit."""
        bpp_id = str(uuid.uuid4())
        so_id  = str(uuid.uuid4())
        sc_id  = str(uuid.uuid4())

        cur.execute(
            """INSERT INTO bpp (bpp_id,name,network_id,endpoint_url,
                                reliability_score,on_time_delivery_rate,
                                registered_at,last_seen_at)
               VALUES (%s,'Tmp','test-tmp.ondc','https://tmp.local',
                       0.5,0.5,NOW(),NOW())""",
            (bpp_id,),
        )
        cur.execute(
            """INSERT INTO seller_offerings
                   (offering_id,query_id,bpp_id,item_id,price,currency,
                    delivery_eta_hours,is_normalized)
               VALUES (%s,%s,%s,'TMP-ITEM',100.00,'INR',24,TRUE)""",
            (so_id, workflow_ids["query_id"], bpp_id),
        )
        cur.execute(
            """INSERT INTO scored_offers
                   (score_id,offering_id,rank,total_score,tco_value,
                    explanation_text,model_version)
               VALUES (%s,%s,99,50.0,100.00,'tmp','test-v1')""",
            (sc_id, so_id),
        )
        conn.commit()

        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO negotiation_outcomes
                       (negotiation_id,score_id,strategy_applied,
                        initial_price,final_price,discount_percent,acceptance_status)
                   VALUES (%s,%s,'aggressive',100.00,75.00,25.0,'accepted')""",
                (str(uuid.uuid4()), sc_id),
            )
            conn.commit()
        conn.rollback()

        # Cleanup temporary chain
        cur.execute("DELETE FROM scored_offers    WHERE score_id    = %s", (sc_id,))
        cur.execute("DELETE FROM seller_offerings WHERE offering_id = %s", (so_id,))
        cur.execute("DELETE FROM bpp              WHERE bpp_id      = %s", (bpp_id,))
        conn.commit()

    def test_scored_offer_total_score_above_100(self, cur, conn, workflow_ids):
        so_id = str(uuid.uuid4())
        bpp_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO bpp (bpp_id,name,network_id,endpoint_url,
                                reliability_score,on_time_delivery_rate,
                                registered_at,last_seen_at)
               VALUES (%s,'Tmp2','test-tmp2.ondc','https://tmp2.local',
                       0.5,0.5,NOW(),NOW())""",
            (bpp_id,),
        )
        cur.execute(
            """INSERT INTO seller_offerings
                   (offering_id,query_id,bpp_id,item_id,price,currency,
                    delivery_eta_hours,is_normalized)
               VALUES (%s,%s,%s,'TMP2-ITEM',200.00,'INR',24,TRUE)""",
            (so_id, workflow_ids["query_id"], bpp_id),
        )
        conn.commit()

        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO scored_offers
                       (score_id,offering_id,rank,total_score,tco_value,
                        explanation_text,model_version)
                   VALUES (%s,%s,1,150.0,200.00,'bad score','test-v1')""",
                (str(uuid.uuid4()), so_id),
            )
            conn.commit()
        conn.rollback()

        cur.execute("DELETE FROM seller_offerings WHERE offering_id = %s", (so_id,))
        cur.execute("DELETE FROM bpp              WHERE bpp_id      = %s", (bpp_id,))
        conn.commit()

    def test_beckn_intent_budget_range_invalid(self, cur, conn, workflow_ids):
        pr_id = str(uuid.uuid4())
        pi_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO procurement_requests
                   (request_id,requester_id,raw_input_text,channel,status)
               VALUES (%s,%s,'TEST: budget range test','web','draft')""",
            (pr_id, workflow_ids["requester_id"]),
        )
        cur.execute(
            """INSERT INTO parsed_intents
                   (intent_id,request_id,intent_class,confidence_score,model_version)
               VALUES (%s,%s,'procurement',0.95,'test-v1')""",
            (pi_id, pr_id),
        )
        conn.commit()

        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO beckn_intents
                       (beckn_intent_id,intent_id,item,quantity,unit,
                        location_coordinates,delivery_timeline_hours,
                        budget_min,budget_max,currency)
                   VALUES (%s,%s,'TEST-bad-budget',10,'units',
                           '12.9716,77.5946',48, 2000.00,500.00,'INR')""",
                (str(uuid.uuid4()), pi_id),
            )
            conn.commit()
        conn.rollback()

        cur.execute("DELETE FROM parsed_intents        WHERE intent_id  = %s", (pi_id,))
        cur.execute("DELETE FROM procurement_requests  WHERE request_id = %s", (pr_id,))
        conn.commit()

    # ── UNIQUE constraints ────────────────────────────────────────────────────

    def test_user_email_unique(self, cur, conn):
        email = f"test_uniq_{uuid.uuid4().hex[:8]}@test.local"
        uid1, uid2 = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute(
            """INSERT INTO users(user_id,email,name,role,department,keycloak_id,idp_provider)
               VALUES(%s,%s,'A','requester','IT',%s,'keycloak')""",
            (uid1, email, f"kc-{uid1}"),
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """INSERT INTO users(user_id,email,name,role,department,keycloak_id,idp_provider)
                   VALUES(%s,%s,'B','requester','IT',%s,'keycloak')""",
                (uid2, email, f"kc-{uid2}"),
            )
            conn.commit()
        conn.rollback()
        cur.execute("DELETE FROM users WHERE user_id=%s", (uid1,))
        conn.commit()

    def test_purchase_order_beckn_ref_unique(self, cur, conn, workflow_ids):
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """INSERT INTO purchase_orders
                       (po_id,approval_id,bpp_id,item_id,quantity,unit,
                        agreed_price,currency,delivery_terms,beckn_confirm_ref,status)
                   VALUES (%s,%s,%s,'DUP',1,'units',100.00,'INR','terms',
                           %s,'pending')""",
                (
                    str(uuid.uuid4()),
                    workflow_ids["approval_id"],     # will fail UNIQUE on approval_id too
                    workflow_ids["bpp_id"],
                    workflow_ids["beckn_confirm_ref"],
                ),
            )
            conn.commit()
        conn.rollback()

    # ── FK constraints ────────────────────────────────────────────────────────

    def test_procurement_request_invalid_user_fk(self, cur, conn):
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO procurement_requests
                       (request_id,requester_id,raw_input_text,channel,status)
                   VALUES(%s,%s,'TEST: bad fk','web','draft')""",
                (str(uuid.uuid4()), str(uuid.uuid4())),
            )
            conn.commit()
        conn.rollback()

    def test_seller_offering_invalid_bpp_fk(self, cur, conn, workflow_ids):
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO seller_offerings
                       (offering_id,query_id,bpp_id,item_id,price,currency,
                        delivery_eta_hours,is_normalized)
                   VALUES(%s,%s,%s,'X',99.00,'INR',24,TRUE)""",
                (
                    str(uuid.uuid4()),
                    workflow_ids["query_id"],
                    str(uuid.uuid4()),  # non-existent BPP
                ),
            )
            conn.commit()
        conn.rollback()

    # ── ERP sync CHECK constraint ─────────────────────────────────────────────

    def test_erp_budget_check_requires_budget_available(self, cur, conn, workflow_ids):
        """budget_check records must have budget_available set (not NULL)."""
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO erp_sync_records
                       (sync_id,po_id,erp_system,sync_type,status,budget_available)
                   VALUES(%s,%s,'sap_s4hana','budget_check','pending',NULL)""",
                (str(uuid.uuid4()), workflow_ids["po_id"]),
            )
            conn.commit()
        conn.rollback()
