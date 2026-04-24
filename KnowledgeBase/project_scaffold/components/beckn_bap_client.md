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
