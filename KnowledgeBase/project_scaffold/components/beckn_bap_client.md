---
tags: [component, beckn, protocol, ondc, bap, async, catalog-normalization, beckn-onix, microservice, lambda]
cssclasses: [procurement-doc, component-doc]
status: "#implemented"
related: ["[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[microservices_architecture]]", "[[negotiation_engine]]", "[[phase1_foundation_protocol_integration]]", "[[phase2_core_intelligence_transaction_flow]]"]
---

# Component: Beckn BAP Client

> [!architecture] Role in the System
> `services/beckn-bap-client/` is **Lambda 2** in the Step Functions state machine. It is a standalone aiohttp microservice on port 8002 that handles all Beckn protocol communication (discover + select) and receives async ONIX callbacks. Called by the orchestrator at steps 2 and 4.

## HTTP Interface

### Orchestrator-facing routes

```
POST /discover
Body:     BecknIntent JSON (item, quantity, location_coordinates, …)
Response: { "transaction_id": str, "offerings": [DiscoverOffering…] }

POST /select
Body:     { "transaction_id", "bpp_id", "bpp_uri", "item_id", "item_name",
            "provider_id", "price_value", "price_currency", "quantity" }
Response: { "ack": "ACK" | "NACK" }
```

### ONIX callback receiver (same port 8002)

```
POST /bap/receiver/{action}    on_discover, on_select, on_init, on_confirm, on_status
POST /{action}                 real Beckn network direct callbacks
```

```
GET /health
Response: { "status": "ok", "service": "beckn-bap-client", "bap_id": str }
```

## Core Transaction Flows

### `discover` — Discovery (Beckn v2)
- Python BAP layer calls `POST /bap/caller/discover` on the ONIX adapter with a structured `BecknIntent`.
- ONIX adapter routes the request to the local catalog endpoint (`/bpp/discover` on `src/server.py`), which ACKs immediately and fires an async `on_discover` callback to `POST /bap/receiver/on_discover`.
- `BecknClient.discover_async()` blocks on a `CallbackCollector` queue until the callback arrives (configurable timeout, default 10s).
- Responses feed into the **Catalog Normalization Layer** (below).

### `publish` — Catalog Registration (BPP-side)
- BPPs register/update their product catalog by calling `POST /publish` to the Catalog Service.
- The BAP system does not initiate this — BPPs do it proactively when their catalog changes.
- The Catalog Service indexes offerings for efficient `discover` queries.

### `/select` — Negotiation Signal
- Python agent calls `POST /bap/caller/select` → ONIX routes to `POST /bpp/receiver/select`.
- Signals buyer interest in specific offers; allows the [[negotiation_engine|Negotiation Engine]] to propose modified terms.

### `/init` — Order Initialization
- Python agent calls `POST /bap/caller/init` → initiates the order with the selected seller.

### `/confirm` — Order Confirmation
- Python agent calls `POST /bap/caller/confirm` → places the confirmed order.
- Triggers [[event_streaming_kafka|Kafka]] publish → [[erp_integration|ERP sync]] + [[audit_trail_system|audit event]] + [[communication_slack_teams|notification dispatch]].

### `/status` — Order Tracking
- Python agent calls `POST /bap/caller/status` → retrieves real-time delivery status.
- Combined with webhooks → feeds [[real_time_tracking]].

## ONIX Endpoint Routing Table

| Action   | Python BAP Layer Calls          | ONIX Routes To                        | Callback to BAP                         |
| -------- | ------------------------------- | ------------------------------------- | --------------------------------------- |
| discover | `POST /bap/caller/discover`     | `/bpp/discover` (local catalog)       | `POST /bap/receiver/on_discover`        |
| select   | `POST /bap/caller/select`       | `POST /bpp/receiver/select`           | `POST /bap/receiver/on_select`          |
| init     | `POST /bap/caller/init`         | `POST /bpp/receiver/init`             | `POST /bap/receiver/on_init`            |
| confirm  | `POST /bap/caller/confirm`      | `POST /bpp/receiver/confirm`          | `POST /bap/receiver/on_confirm`         |
| status   | `POST /bap/caller/status`       | `POST /bpp/receiver/status`           | `POST /bap/receiver/on_status`          |

## Security: ED25519 Signing (beckn-onix)

All Beckn messages are signed automatically by the ONIX adapter:
- `signer.so` plugin attaches ED25519 `Authorization` header to every outbound request.
- `signvalidator.so` plugin validates signatures on every inbound callback.
- In dev mode (local-simple config), keys are pre-configured in YAML — no manual certificate generation required.
- In production: ED25519 key pairs managed via HashiCorp Vault or equivalent KMS.

## Catalog Normalization Layer

Diverse sellers return different catalog formats from `on_discover` callbacks. Normalization is fully handled by the [[catalog_normalizer]] module (`src/normalizer/`) — `BecknClient` delegates to it via a module-level singleton:

```python
_normalizer = CatalogNormalizer()
# inside _build_discover_response():
offerings.extend(_normalizer.normalize({"message": {"catalog": catalog}}, bpp_id, bpp_uri))
```

### Supported Formats

| Variant | Structure | Detection |
|---|---|---|
| `BECKN_V2_FLAT_RESOURCES` (1) | `resources[]` at catalog root (real Beckn v2) | `resources` key is a non-empty list |
| `ONDC_CATALOG` (4) | `fulfillments[]` + `tags[]` present | both keys present |
| `LEGACY_PROVIDERS_ITEMS` (2) | `providers[].items[]` (mock_onix/legacy) | `providers` list with `items` sub-key |
| `BPP_CATALOG_V1` (3) | `items[]` with `provider` as string ID | `items[0]["provider"]` is a string |
| `UNKNOWN` (5) | No fingerprint matched | LLM fallback (instructor + Ollama `qwen3:1.7b`) |

### Module layers (`src/normalizer/`)

- `FormatDetector` — pure function, detects variant via `FINGERPRINT_RULES` (ordered, first-match-wins)
- `SchemaMapper` — deterministic mapping for variants 1–4, no LLM
- `LLMFallbackNormalizer` — instructor + Ollama for unknown formats; returns `[]` on error, never raises
- `CatalogNormalizer` — public facade that orchestrates the 3-step pipeline

**Phase 2 acceptance:** Implementing — 5+ valid formats, 17 unit tests don't need Ollama.

> [!milestone] Phase Delivery
> - **[[phase1_foundation_protocol_integration|Phase 1]] (Weeks 1–4):** beckn-onix adapter deployed; `discover` and `publish` functional against Beckn v2 sandbox; 3+ seller responses parsed.
> - **[[phase2_core_intelligence_transaction_flow|Phase 2]] (Weeks 5–8):** `/init`, `/confirm`, `/status` implemented; full order lifecycle validated.
> - **[[phase3_advanced_intelligence_enterprise_features|Phase 3]] (Weeks 9–12):** Multi-network concurrent queries to 2+ Beckn networks; graceful degradation when one network is down.

## Frontend Integration API

Two HTTP endpoints exposed by `src/server.py` (port 8000) for the Next.js frontend. Both share the same aiohttp server as the Beckn callback receiver — no second Python process required.

### `POST /parse` — NL Intent Parsing

Receives a natural language query from the frontend Step 1 form, runs the IntentParser (Ollama `qwen3:1.7b`), and returns a structured `ParseResult` for the preview step.

**Request:**
```json
{ "query": "500 reams A4 paper 80gsm Bangalore 3 days max 200 INR" }
```

## Internal Structure

```
services/beckn-bap-client/
├── src/
│   ├── beckn/            copied from Bap-1/src/beckn/ (adapter, client, callbacks, models)
│   ├── normalizer/       reconstructed (FormatDetector, SchemaMapper, CatalogNormalizer)
│   ├── config.py         BecknConfig from env vars (ONIX_URL, BAP_URI, BAP_ID, …)
│   └── handler.py        aiohttp server — all three route groups
├── Dockerfile            build context: repo root (to COPY shared/)
└── requirements.txt
```

## Internal Modules

- **`src/beckn/adapter.py`** — `BecknProtocolAdapter`: builds Beckn v2 wire payloads (camelCase context, discover/select wire format). Owns all URL construction.
- **`src/beckn/client.py`** — `BecknClient`: async HTTP layer. `discover_async()` sends to ONIX and awaits the `on_discover` callback via `CallbackCollector`. `select()` returns the ACK dict.
- **`src/beckn/callbacks.py`** — `CallbackCollector`: routes async ONIX callbacks to per-`(transaction_id, action)` asyncio queues.
- **`src/beckn/models.py`** — Beckn v2 Pydantic models. `BecknIntent` and `DiscoverOffering` imported from `shared/models.py` (single source of truth).
- **`src/normalizer/`** — `CatalogNormalizer`: Normalizer Agent embedded in this Lambda. Detects catalog format (flat resources vs nested providers), maps to `DiscoverOffering`, falls back to heuristic/LLM for unknown formats.
- **`src/config.py`** — `BecknConfig(BaseSettings)`: reads `ONIX_URL`, `BAP_URI`, `BAP_ID`, `CALLBACK_TIMEOUT` from env vars.

## ONIX Routing

The ONIX adapter (Go, port 8081) handles ED25519 signing and network routing. The beckn-bap-client never talks to BPPs directly.

ONIX must be configured to send `on_discover` callbacks to:
```
http://beckn-bap-client:8002/bap/receiver/on_discover
```
This is set via `BAP_URI=http://beckn-bap-client:8002` in docker-compose.yml.

## Called By

The orchestrator calls this service as **Step 2** (discover) and **Step 4** (select):
```python
discover_result = POST http://beckn-bap-client:8002/discover  { beckn_intent }
select_result   = POST http://beckn-bap-client:8002/select    { selected + txn_id }
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `ONIX_URL` | `http://localhost:8081` | beckn-onix Go adapter |
| `BAP_URI` | `http://localhost:8002` | This service's public URI (for callbacks) |
| `BAP_ID` | `bap.example.com` | BAP identifier |
| `CALLBACK_TIMEOUT` | `10.0` | Seconds to wait for on_discover callback |
