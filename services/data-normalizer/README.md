# data-normalizer — Central Persistence Layer

aiohttp microservice (port 8006) that is the single write path into PostgreSQL for the entire procurement pipeline. Every service that needs to persist or retrieve data calls this service — it translates HTTP requests into typed database operations via asyncpg.

## Role in the stack

```
intention-parser → /normalize/intent
beckn-bap-client → /normalize/discovery
comparative-scoring → /normalize/scoring
orchestrator → /normalize/order, /normalize/audit, /normalize/memory/*
sim-bpp → PATCH /normalize/po_status
frontend → /admin/users, /approvals, /order/{id}
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| POST | `/normalize/request` | Create a procurement_request from raw text |
| POST | `/normalize/intent` | Persist parsed_intent + beckn_intent after Stage 1+2 |
| POST | `/normalize/discovery` | Persist discovery_query + seller_offerings from catalog |
| POST | `/normalize/scoring` | Persist scored_offers from scoring engine |
| POST | `/normalize/order` | Persist purchase_order after Beckn /confirm |
| GET | `/order/{request_id}` | Retrieve full order detail DTO (404 if not found) |
| POST | `/normalize/audit` | Persist an audit_trail_event |
| GET | `/normalize/audit/{event_id}` | Retrieve a single audit event |
| GET | `/normalize/audit?request_id=X` or `?po_id=X` | List audit events (max 500) |
| PATCH | `/normalize/status` | Update procurement_request.status |
| PATCH | `/normalize/po_status` | Update purchase_order.status by beckn_confirm_ref |
| GET | `/admin/users` | List all users |
| PATCH | `/admin/users/{user_id}` | Update user approval_threshold and/or department |
| GET | `/approvals` | List requests in pending_approval status |
| POST | `/approvals/{request_id}/decide` | Approve or reject a pending request |
| POST | `/normalize/memory/write` | Embed + store a confirmed transaction in agent_memory_vectors |
| POST | `/normalize/memory/search` | ANN search in agent_memory_vectors for past similar transactions |

## Error handling

The `db_error_middleware` maps asyncpg constraint exceptions to structured HTTP errors:

| Exception | HTTP status |
|-----------|-------------|
| UniqueViolationError | 409 |
| ForeignKeyViolationError | 409 |
| CheckViolationError | 422 |
| NotNullViolationError | 422 |
| Other PostgresError | 500 |

## Memory endpoints

`/normalize/memory/write` embeds the payload using `all-MiniLM-L6-v2` (sentence-transformers) and stores as `vector(384)` in `agent_memory_vectors`. Embedding failures are silently skipped — the endpoint never returns an error due to embedding failure alone.

`/normalize/memory/search` performs HNSW ANN cosine search and returns the top-k most similar past transactions.

## Admin notes

- User **role** is NOT updatable here — Keycloak is the source of truth and overwrites the DB role on every login.
- `approval_threshold` and `department` are the only user fields that can be updated via this service.

## Configuration

| Var | Default | Description |
|-----|---------|-------------|
| `PORT` | `8006` | Listen port |
| `DB_HOST` | `localhost` | |
| `DB_PORT` | `5432` | |
| `DB_NAME` | `procurement_agent` | |
| `DB_USER` | `postgres` | |
| `DB_PASSWORD` | `""` | |

## Run

```bash
docker compose up -d data-normalizer
# or
python src/handler.py
```
