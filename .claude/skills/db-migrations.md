---
name: db-migrations
description: PostgreSQL 16 + pgvector schema for the procurement agent. 18 numbered SQL scripts with strict execution order, 16 tables, 21 indexes, 20 ENUM types. Auto-invoke when editing anything under database/, adding a new migration, modifying setup_database.py, or running test_database.py.
tools: Read, Grep, Glob, Edit, Bash
---

# Database migrations — rules of engagement

Canonical doc: `database/README.md`. Setup script: `database/setup_database.py`. Test suite: `database/test_database.py` (67 assertions across 8 classes).

## Strict execution order

Files in `database/sql/` are sorted **lexicographically** by `setup_database.py`. The numeric prefix is load-bearing. FK dependency chain (do NOT reorder):

```
00 extensions + ENUM types (no deps)
01 users                   (no FK)
02 bpp                     (no FK — referenced by offerings & POs, so defined early)
03 procurement_requests    → users
04 parsed_intents          → procurement_requests
05 beckn_intents           → parsed_intents
06 discovery_queries       → beckn_intents
07 catalog_cache           → discovery_queries
08 seller_offerings        → discovery_queries, bpp
09 scored_offers           → seller_offerings
10 negotiation_outcomes    → scored_offers
11 approval_decisions      → negotiation_outcomes, users ×2
12 purchase_orders         → approval_decisions, bpp
13 erp_sync_records        → purchase_orders
14 audit_trail_events      → procurement_requests, purchase_orders, users (all nullable)
15 agent_memory_vectors    → procurement_requests (nullable)
16 model_governance_records (no FK)
17 indexes                 (depends on every table existing)
18 bpp_catalog_semantic_cache (added later — IntentParser Stage 3)
```

**To add a migration:** create `19_your_change.sql` (next free number). All `CREATE TABLE` and `CREATE INDEX` MUST use `IF NOT EXISTS` — re-running existing scripts is idempotent and that property is relied on by `python setup_database.py` (without `--drop-all`).

## Multi-store invariants

- `catalog_cache` — **primary store is Redis 7** (key `{item_normalized}:{lat}:{lon}`, TTL 15 min). The PG table is an audit mirror; `expires_at` is informational only. Never rely on PG row existence as a cache hit.
- `agent_memory_vectors` — **primary store is Qdrant**. The PG table uses `vector(3072)` (pgvector) and is kept in sync via a Kafka consumer.
- `bpp_catalog_semantic_cache` (file 18) — primary store IS PG; uses `vector(384)` for `all-MiniLM-L6-v2` embeddings, queried with HNSW ANN at `ef_search=100`. Used by IntentParser Stage 3.

## Index conventions to preserve

The 22 indexes in `17_indexes.sql` use **partial indexes with CHECK predicates** to keep them lean. Examples to keep consistent when adding new ones:

- Active rows only: `WHERE status NOT IN ('confirmed','cancelled')`
- Pending work queues: `WHERE status = 'pending'`
- Audit traceability: `WHERE request_id IS NOT NULL`
- Override calibration: `WHERE user_overridden = TRUE`

Composite indexes are ordered for the dominant query (most-selective column first, sort column last with `DESC` if used in `ORDER BY`).

## Setup commands

```bash
cd database/
export $(grep -v '^#' .env | xargs)         # required: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

python setup_database.py --create-db        # first-time
python setup_database.py --drop-all         # clean rebuild (DESTRUCTIVE)
python setup_database.py --create-db --drop-all   # combined
python setup_database.py                    # idempotent re-run after adding scripts
```

Don't use `psql -c "DROP DATABASE"` etc. — use the script's flags so behaviour stays consistent across environments.

## Tests (`database/test_database.py`)

| Class | What it asserts |
|---|---|
| `TestConnection` | Server is reachable and is PostgreSQL |
| `TestExtensions` | `uuid-ossp`, `pgcrypto`, `vector` installed |
| `TestEnumTypes` | 20 ENUM types in `public` |
| `TestTables` | 16 tables in `public` |
| `TestIndexes` | 21 named indexes exist |
| `TestWorkflowRows` | All 16 entities accept inserts with the expected field values |
| `TestEndToEndQuery` | A 12-table JOIN returns the full procurement chain |
| `TestConstraints` | CHECK / UNIQUE / FK violations rejected with the right `psycopg2` error class |

The session-scoped `workflow_ids` fixture inserts the full chain at session start and deletes it in **reverse FK order** at teardown. New tables → extend the fixture if they belong to the chain.

```bash
pytest database/test_database.py -v                          # all
pytest database/test_database.py::TestConstraints -v         # one class
pytest database/test_database.py -v --tb=short -q            # compact
```

When adding a new table, you typically need to update three places: `database/sql/NN_*.sql` + the `TestTables` count + the `workflow_ids` fixture if FK-linked.

## Connection config

All paths read these env vars (no fallback to a `.env` file unless you opt in via `python-dotenv` or `export $(grep -v '^#' .env | xargs)`):

`DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD`

`IntentParser/config.py` adds `DB_SSL`, `DB_MIN_POOL`, `DB_MAX_POOL`, `DB_CMD_TIMEOUT`, `HNSW_EF_SEARCH=100` (set via the asyncpg pool init callback in `IntentParser/db.py`).
