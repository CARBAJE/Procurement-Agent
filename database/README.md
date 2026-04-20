# Procurement Agent — PostgreSQL Database

Complete PostgreSQL schema setup, automation, and integration tests for the **Agentic AI Procurement Agent on Beckn Protocol** system.

---

## Table of Contents

1. [Requirements](#1-requirements)
2. [Folder structure](#2-folder-structure)
3. [Environment variables and `.env`](#3-environment-variables-and-env)
4. [Setup script — `setup_database.py`](#4-setup-script--setup_databasepy)
5. [SQL scripts execution order](#5-sql-scripts-execution-order)
6. [Entity overview](#6-entity-overview)
7. [Multi-store notes (Redis / Qdrant)](#7-multi-store-notes-redis--qdrant)
8. [Index rationale](#8-index-rationale)
9. [Test suite — `test_database.py`](#9-test-suite--test_databasepy)
10. [Common operations](#10-common-operations)

---

## 1. Requirements

| Dependency | Minimum version | Purpose |
|---|---|---|
| PostgreSQL | 16 | Database engine |
| pgvector extension | 0.7.0 | `vector(3072)` type for `agent_memory_vectors` |
| Python | 3.10 | Setup and test scripts |
| psycopg2-binary | 2.9 | PostgreSQL adapter for Python |
| pytest | 7.0 | Test runner |

Install Python dependencies:

```bash
pip install psycopg2-binary pytest
```

Install pgvector on PostgreSQL (requires superuser):

```bash
# Debian / Ubuntu
sudo apt install postgresql-16-pgvector

# macOS (Homebrew)
brew install pgvector
```

Then enable it inside the target database — the setup script does this automatically via `00_extensions_and_types.sql`.

---

## 2. Folder structure

```
database/
├── .env                        ← Connection variables (copy and fill in)
├── .env.example                ← Reference template (safe to commit)
├── setup_database.py           ← Python automation: runs all SQL scripts in order
├── test_database.py            ← pytest integration tests
└── sql/
    ├── 00_extensions_and_types.sql   ← Extensions (uuid-ossp, pgcrypto, vector) + 20 ENUM types
    ├── 01_users.sql                  ← Entity 1:  User
    ├── 02_bpp.sql                    ← Entity 7:  BPP (defined early — referenced by offerings and POs)
    ├── 03_procurement_requests.sql   ← Entity 2:  ProcurementRequest
    ├── 04_parsed_intents.sql         ← Entity 3:  ParsedIntent
    ├── 05_beckn_intents.sql          ← Entity 4:  BecknIntent
    ├── 06_discovery_queries.sql      ← Entity 5:  DiscoveryQuery
    ├── 07_catalog_cache.sql          ← Entity 6:  CatalogCache (PostgreSQL audit mirror of Redis)
    ├── 08_seller_offerings.sql       ← Entity 8:  SellerOffering
    ├── 09_scored_offers.sql          ← Entity 9:  ScoredOffer
    ├── 10_negotiation_outcomes.sql   ← Entity 10: NegotiationOutcome
    ├── 11_approval_decisions.sql     ← Entity 11: ApprovalDecision
    ├── 12_purchase_orders.sql        ← Entity 12: PurchaseOrder
    ├── 13_erp_sync_records.sql       ← Entity 13: ERPSyncRecord
    ├── 14_audit_trail_events.sql     ← Entity 14: AuditTrailEvent
    ├── 15_agent_memory_vectors.sql   ← Entity 15: AgentMemoryVector (pgvector mirror of Qdrant)
    ├── 16_model_governance_records.sql ← Entity 16: ModelGovernanceRecord
    └── 17_indexes.sql                ← 22 operational and audit indexes
```

The numeric prefix determines execution order. The setup script sorts files lexicographically, so `00_` always runs before `01_`, and so on.

---

## 3. Environment variables and `.env`

The setup script and the test suite read database credentials from environment variables. A `.env` file is provided as a convenience — its values are **not** loaded automatically by Python; you must export them to the shell before running the scripts.

### The `.env` file

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=procurement_agent
DB_USER=postgres
DB_PASSWORD=your_password_here
```

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL server hostname or IP |
| `DB_PORT` | `5432` | PostgreSQL server port |
| `DB_NAME` | `procurement_agent` | Target database name |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | _(empty)_ | PostgreSQL password |

### How to load the `.env` into your shell

**Option A — export manually (any shell):**

```bash
export $(grep -v '^#' .env | xargs)
```

**Option B — use `python-dotenv` (load inside Python):**

```bash
pip install python-dotenv
```

Then prepend this to `setup_database.py` or `test_database.py` before running, or add it to your own wrapper:

```python
from dotenv import load_dotenv
load_dotenv()   # reads .env in the current directory
```

**Option C — pass variables inline (one-shot, no export needed):**

```bash
DB_HOST=localhost DB_PORT=5432 DB_NAME=procurement_agent \
DB_USER=postgres DB_PASSWORD=secret python setup_database.py --create-db
```

> **Security note:** never commit `.env` with real credentials. The `.gitignore` at the project root already excludes `.env` files. Commit only the `.env` file as a template with placeholder values.

---

## 4. Setup script — `setup_database.py`

The script connects to PostgreSQL and executes every `.sql` file inside `./sql/` in lexicographic order. Each file runs in a single transaction; if any script fails the transaction is rolled back and the process exits with a non-zero code.

### Flags

| Flag | Effect |
|---|---|
| _(none)_ | Connect and execute all SQL scripts against an existing database. |
| `--create-db` | Connect to the `postgres` system database first and create `DB_NAME` if it does not exist, then proceed with the scripts. Requires the user to have `CREATEDB` privilege. |
| `--drop-all` | Drop **all** tables and ENUM types in the `public` schema (CASCADE) before executing the scripts. Useful for a clean rebuild. **Destructive — all data will be lost.** |

The two flags are independent and can be combined:

```bash
# Most common first-time setup
export $(grep -v '^#' .env | xargs)
python setup_database.py --create-db

# Full reset and rebuild (CI / local dev)
python setup_database.py --drop-all

# Create DB and immediately rebuild
python setup_database.py --create-db --drop-all
```

### Expected output

```
═══════════════════════════════════════════════════════
  Procurement Agent — PostgreSQL Database Setup
═══════════════════════════════════════════════════════
  Target : postgres@localhost:5432/procurement_agent

Step 1 — Create database
  Created database 'procurement_agent'.

Connecting to database...
  Connected to 'procurement_agent'.

Step 3 — Executing 18 SQL scripts
  [OK]   00_extensions_and_types.sql
  [OK]   01_users.sql
  ...
  [OK]   17_indexes.sql

═══════════════════════════════════════════════════════
  Setup complete — 18 scripts executed successfully.
═══════════════════════════════════════════════════════
```

---

## 5. SQL scripts execution order

Scripts must be executed in numeric order because of foreign key dependencies. The setup script handles this automatically.

```
00  Extensions + ENUM types        (no dependencies)
01  users                          (no FK dependencies)
02  bpp                            (no FK dependencies)
03  procurement_requests           → users
04  parsed_intents                 → procurement_requests
05  beckn_intents                  → parsed_intents
06  discovery_queries              → beckn_intents
07  catalog_cache                  → discovery_queries
08  seller_offerings               → discovery_queries, bpp
09  scored_offers                  → seller_offerings
10  negotiation_outcomes           → scored_offers
11  approval_decisions             → negotiation_outcomes, users ×2
12  purchase_orders                → approval_decisions, bpp
13  erp_sync_records               → purchase_orders
14  audit_trail_events             → procurement_requests, purchase_orders, users (all nullable)
15  agent_memory_vectors           → procurement_requests (nullable)
16  model_governance_records       (no FK dependencies)
17  indexes                        (depends on all tables existing)
```

Running the scripts manually in psql:

```bash
for f in sql/*.sql; do
    psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f "$f" && echo "OK: $f" || { echo "FAIL: $f"; break; }
done
```

---

## 6. Entity overview

| # | Table | Primary store | Key relationships |
|---|---|---|---|
| 1 | `users` | PostgreSQL | Root of RBAC; referenced by requests, approvals, and audit events |
| 2 | `procurement_requests` | PostgreSQL | Root of the decision chain; FK → `users` |
| 3 | `parsed_intents` | PostgreSQL | 1:1 with `procurement_requests`; stage-1 NL parser output |
| 4 | `beckn_intents` | PostgreSQL | 1:1 with `parsed_intents`; anti-corruption layer for Beckn protocol |
| 5 | `discovery_queries` | PostgreSQL | Many per `beckn_intent`; records each `GET /discover` call |
| 6 | `catalog_cache` | **Redis** (mirror here) | Keyed by `{item}:{lat}:{lon}`; TTL 15 min in Redis |
| 7 | `bpp` | PostgreSQL | Beckn Provider Platforms (sellers); referenced by offerings and POs |
| 8 | `seller_offerings` | PostgreSQL | Normalized BPP responses; FK → `discovery_queries` + `bpp` |
| 9 | `scored_offers` | PostgreSQL | 1:1 with `seller_offerings`; Scoring Engine output |
| 10 | `negotiation_outcomes` | PostgreSQL | 1:1 with `scored_offers`; Beckn `/select` result; max discount 20% |
| 11 | `approval_decisions` | PostgreSQL | 1:1 with `negotiation_outcomes`; RBAC state machine |
| 12 | `purchase_orders` | PostgreSQL | 1:1 with `approval_decisions`; Beckn `/confirm` result |
| 13 | `erp_sync_records` | PostgreSQL | Many per `purchase_orders`; SAP/Oracle sync operations |
| 14 | `audit_trail_events` | PostgreSQL + Splunk | Every agent decision; 7-year retention (SOX 404 / GDPR) |
| 15 | `agent_memory_vectors` | **Qdrant** (mirror here) | `vector(3072)` embeddings via pgvector; feeds RAG |
| 16 | `model_governance_records` | PostgreSQL | Weekly AI model evaluation registry |

---

## 7. Multi-store notes (Redis / Qdrant)

Two entities have a **primary store outside PostgreSQL**. Their PostgreSQL tables serve as audit mirrors and referential integrity anchors.

### `catalog_cache` — primary store: Redis 7

- Redis key: `{item_normalized}:{lat}:{lon}` — TTL 15 minutes.
- The PostgreSQL `catalog_cache` table is written by the Discovery Service alongside Redis to provide an audit record and allow JOIN queries.
- TTL enforcement is Redis-only; the `expires_at` column is informational.

### `agent_memory_vectors` — primary store: Qdrant

- Qdrant stores vectors with an HNSW index; target retrieval latency < 100 ms.
- The PostgreSQL `agent_memory_vectors` table holds the same records using the `vector(3072)` type from the **pgvector** extension. It is kept in sync by the Qdrant Indexer Kafka consumer.
- The `embedding_vector` column enables SQL-side vector similarity queries and offline analytics without hitting Qdrant.

---

## 8. Index rationale

All 22 indexes are defined in `17_indexes.sql`. The table below explains why each index exists and which workload it supports.

### `procurement_requests`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_procurement_requests_requester` | `(requester_id, created_at DESC)` | — | Dashboard: list a user's requests ordered by most recent. Composite avoids a sort step. |
| `idx_procurement_requests_status` | `(status)` | `status NOT IN ('confirmed','cancelled')` | Partial index covers only active requests (~20% of rows over time), keeping it small and fast for the agent orchestrator status poll. |

### `audit_trail_events`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_audit_events_request` | `(request_id, event_timestamp)` | `request_id IS NOT NULL` | Primary traceability query: retrieve full decision chain for a given request. Partial excludes system events with no request. |
| `idx_audit_events_type` | `(event_type, event_timestamp)` | — | SOX/GDPR reporting: "show all confirm events in date range X–Y". |
| `idx_audit_events_po` | `(po_id, event_timestamp)` | `po_id IS NOT NULL` | Post-confirmation event lookup per PO. Partial excludes pre-confirm events. |
| `idx_audit_events_splunk_pending` | `(splunk_indexed, event_timestamp)` | `splunk_indexed = FALSE` | Batch job that pushes unsent events to Splunk/ServiceNow reads this; partial index contains only the pending rows. |

### `seller_offerings`

| Index | Columns | Rationale |
|---|---|---|
| `idx_seller_offerings_query` | `(query_id)` | Fetch all offerings returned by a discovery query (many-to-one join). |
| `idx_seller_offerings_bpp` | `(bpp_id)` | Historical offering lookup per seller; used by Agent Memory for supplier profiling. |

### `scored_offers`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_scored_offers_overridden` | `(user_overridden, scored_at)` | `user_overridden = TRUE` | Model calibration job: counts overrides in a rolling 30-day window. Partial index contains only the overridden rows, which are expected to be < 30% of total. |

### `purchase_orders`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_purchase_orders_bpp` | `(bpp_id, status)` | `status NOT IN ('delivered','cancelled')` | Seller relationship view: active orders per BPP. Partial keeps the index lean as the majority of rows are eventually terminal. |
| `idx_purchase_orders_status` | `(status, created_at DESC)` | — | Operations dashboard sorted by creation date. |

### `model_governance_records`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_model_governance_name` | `(model_name, evaluation_date DESC)` | — | Fetch the latest evaluation record for a given model; used by the weekly pipeline and the governance dashboard. |
| `idx_model_governance_status` | `(status)` | `status <> 'deprecated'` | Alert queries scan for `active` and `review_triggered` models. Partial excludes deprecated historical records. |

### `bpp`

| Index | Columns | Rationale |
|---|---|---|
| `idx_bpp_network` | `(network_id)` | Discovery Service looks up sellers by Beckn network ID before inserting or updating BPP records. |

### `erp_sync_records`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_erp_sync_po` | `(po_id, sync_type)` | — | Retrieve the full sync history for a PO grouped by operation type (budget_check, po_creation, etc.). |
| `idx_erp_sync_pending` | `(status, synced_at)` | `status = 'pending'` | Retry queue: the ERP Consumer polls for pending records. Partial index contains only the rows that need processing. |

### `discovery_queries`

| Index | Columns | Rationale |
|---|---|---|
| `idx_discovery_queries_intent` | `(beckn_intent_id, queried_at DESC)` | Fetch all discovery attempts for a given intent, most recent first. Supports retry logic and cache-hit analysis. |

### `approval_decisions`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_approval_decisions_status` | `(status)` | `status IN ('pending','escalated')` | Approver dashboard and escalation monitor read only open decisions. Partial index is small relative to historical `approved`/`rejected` records. |
| `idx_approval_decisions_approver` | `(approver_id, status)` | `approver_id IS NOT NULL` | Approver inbox: "show me my pending decisions". Partial excludes auto-approvals where `approver_id IS NULL`. |

### `agent_memory_vectors`

| Index | Columns | Predicate | Rationale |
|---|---|---|---|
| `idx_agent_memory_entity_type` | `(entity_type)` | — | RAG routing: the retrieval layer filters by entity type before performing a vector similarity search. |
| `idx_agent_memory_request` | `(source_request_id)` | `source_request_id IS NOT NULL` | Fetch all embeddings generated from a specific request (e.g., to delete them on GDPR right-to-erasure). Partial excludes externally sourced embeddings. |

---

## 9. Test suite — `test_database.py`

### What is tested

| Test class | Assertions |
|---|---|
| `TestConnection` | Can open a connection; server is PostgreSQL |
| `TestExtensions` | `uuid-ossp`, `pgcrypto`, `vector` are installed |
| `TestEnumTypes` | All 20 custom ENUM types exist in `public` schema |
| `TestTables` | All 16 tables exist in `public` schema |
| `TestIndexes` | All 21 named indexes exist |
| `TestWorkflowRows` | Each of the 16 entities has the correct field values after insert |
| `TestEndToEndQuery` | A single 12-table JOIN returns the full procurement chain with correct values |
| `TestConstraints` | CHECK, UNIQUE, and FK violations are rejected with the correct PostgreSQL error class |

### Running the tests

```bash
# From the database/ directory
export $(grep -v '^#' .env | xargs)
pytest test_database.py -v
```

Compact output (show only failures):

```bash
pytest test_database.py -v --tb=short -q
```

Run a single test class:

```bash
pytest test_database.py::TestConstraints -v
```

### Test data lifecycle

The `workflow_ids` fixture (session-scoped) inserts a complete end-to-end procurement chain at the start of the session and deletes it in reverse FK order at teardown. Tests never leave data behind.

Constraint tests that need an independent chain create their own temporary rows and clean them up within the test function itself.

### Expected output (all passing)

```
collected 67 items

test_database.py::TestConnection::test_can_connect            PASSED
test_database.py::TestConnection::test_is_postgresql          PASSED
test_database.py::TestExtensions::test_extension_installed[uuid-ossp]  PASSED
...
test_database.py::TestEndToEndQuery::test_full_procurement_chain  PASSED
test_database.py::TestConstraints::test_bpp_reliability_score_above_1  PASSED
...
67 passed in X.XXs
```

---

## 10. Common operations

### First-time setup

```bash
cd database/
cp .env .env.local            # optional: keep a local override
export $(grep -v '^#' .env | xargs)
python setup_database.py --create-db
pytest test_database.py -v
```

### Rebuild from scratch (development)

```bash
export $(grep -v '^#' .env | xargs)
python setup_database.py --drop-all
pytest test_database.py -v
```

### Apply new SQL scripts without dropping (migrations)

Add your new script as `18_your_change.sql` inside `sql/`, then:

```bash
export $(grep -v '^#' .env | xargs)
python setup_database.py        # --create-db and --drop-all are not needed
```

Because every `CREATE TABLE` and `CREATE INDEX` uses `IF NOT EXISTS`, re-running the existing scripts is idempotent.

### Connect with psql

```bash
source .env   # or export $(...) as above
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME
```

### Check which tables exist

```sql
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
```

### Check which indexes exist

```sql
SELECT indexname, tablename FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname;
```
