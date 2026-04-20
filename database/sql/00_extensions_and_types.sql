-- 00_extensions_and_types.sql
-- PostgreSQL extensions and custom ENUM types for Procurement Agent Beckn Protocol.
-- Must be executed first. Requires superuser for extensions.

-- ──────────────────────────────────────────────────────────────────────────────
-- EXTENSIONS
-- ──────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid(), crypt()
CREATE EXTENSION IF NOT EXISTS "vector";      -- pgvector: vector(3072) for agent_memory_vectors

-- ──────────────────────────────────────────────────────────────────────────────
-- ENUM TYPES
-- ──────────────────────────────────────────────────────────────────────────────

-- Entity: User
CREATE TYPE user_role AS ENUM (
    'requester',
    'approver',
    'admin'
);

CREATE TYPE idp_provider_type AS ENUM (
    'keycloak',
    'okta',
    'azure_ad'
);

-- Entity: ProcurementRequest
CREATE TYPE channel_type AS ENUM (
    'web',
    'slack',
    'teams'
);

CREATE TYPE procurement_status AS ENUM (
    'draft',
    'parsing',
    'discovering',
    'scoring',
    'negotiating',
    'pending_approval',
    'confirmed',
    'cancelled'
);

-- Entity: ParsedIntent
CREATE TYPE intent_class_type AS ENUM (
    'procurement',
    'query',
    'support',
    'out_of_scope'
);

-- Entity: NegotiationOutcome
CREATE TYPE negotiation_strategy_type AS ENUM (
    'aggressive',
    'accept_margin',
    'advisory',
    'escalate',
    'skipped'
);

CREATE TYPE acceptance_status_type AS ENUM (
    'accepted',
    'rejected',
    'advisory',
    'escalated',
    'skipped'
);

-- Entity: ApprovalDecision
CREATE TYPE approval_level_type AS ENUM (
    'auto',
    'manager',
    'cfo'
);

CREATE TYPE approval_status_type AS ENUM (
    'pending',
    'approved',
    'rejected',
    'escalated',
    'auto_approved'
);

CREATE TYPE notification_channel_type AS ENUM (
    'slack',
    'teams',
    'email'
);

-- Entity: PurchaseOrder
CREATE TYPE po_status_type AS ENUM (
    'pending',
    'confirmed',
    'shipped',
    'delivered',
    'cancelled'
);

-- Entity: ERPSyncRecord
CREATE TYPE erp_system_type AS ENUM (
    'sap_s4hana',
    'oracle_erp_cloud'
);

CREATE TYPE erp_sync_type AS ENUM (
    'budget_check',
    'po_creation',
    'goods_receipt',
    'invoice_matching'
);

CREATE TYPE erp_sync_status AS ENUM (
    'success',
    'failed',
    'pending'
);

-- Entity: AuditTrailEvent
CREATE TYPE audit_event_type AS ENUM (
    'discover',
    'normalize',
    'score',
    'negotiate',
    'approve',
    'confirm',
    'override',
    'erp_sync',
    'notification'
);

-- Entity: AgentMemoryVector
CREATE TYPE memory_entity_type AS ENUM (
    'transaction',
    'negotiation',
    'seasonal',
    'supplier',
    'override'
);

CREATE TYPE embedding_model_type AS ENUM (
    'text-embedding-3-large',
    'e5-large-v2'
);

-- Entity: ModelGovernanceRecord
CREATE TYPE model_name_type AS ENUM (
    'intent_parsing',
    'comparison_scoring',
    'negotiation_strategy',
    'memory_retrieval'
);

CREATE TYPE ai_provider_type AS ENUM (
    'openai',
    'anthropic'
);

CREATE TYPE governance_status_type AS ENUM (
    'active',
    'review_triggered',
    'deprecated'
);
