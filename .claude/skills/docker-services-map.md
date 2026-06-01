---
name: docker-services-map
description: Service topology — 11 services, ports, env vars, network. Auto-invoke when running docker compose commands, debugging port collisions or network reachability, editing docker-compose.yml, or wiring a new service into the stack.
tools: Read, Grep, Glob, Edit, Bash
---

# Docker service map

Source: `docker-compose.yml`. Network: `beckn_network` (bridge). All Docker services reach each other by service name; local services reach Docker services via the exposed host ports below.

## Port table

| Port | Service | Where it runs | Purpose |
|---|---|---|---|
| 3000 | `mcp-sidecar` | local Python (uvicorn) | MCP SSE — `search_bpp_catalog` tool |
| 8001 | `intention-parser` | Docker / local | NL → BecknIntent pipeline |
| 8002 | `beckn-bap-client` | Docker | Beckn BAP, ONIX bridge, on_discover publisher |
| 8003 | `comparative-scoring` | Docker | offer ranking |
| 8004 | `orchestrator` | Docker | workflow coordinator (Step Functions sim) |
| 8005 | `catalog-normalizer` | Docker | ONIX catalog parsing |
| 6379 | `redis` | Docker | Pub/Sub broker + ONIX cache |
| 8081 | `onix-bap` | Docker (Go) | Beckn BAP ONIX adapter |
| 8082 | `onix-bpp` | Docker (Go) | Beckn BPP ONIX adapter |
| 3002 | `sandbox-bpp` | Docker (Node) | Mock BPP for select/init/confirm |
| 8000 | `orchestrator` (alt) | Docker | duplicate of 8004 — frontend default |

`mcp-sidecar` and `IntentParser` are NOT in `docker-compose.yml` — run them locally inside `conda activate infosys_project` so the developer can edit Python sources without rebuilding images.

## Critical env-var mappings

Docker network names (used inside containers):

```
http://intention-parser:8001
http://beckn-bap-client:8002
http://onix-bap:8081
http://onix-bpp:8082
http://catalog-normalizer:8005
http://sandbox-bpp:3002
redis://redis:6379       # for Python (REDIS_URL)
redis:6379               # for Go ONIX (REDIS_ADDR — different format)
```

Local-host equivalents (used by `mcp-sidecar` and `IntentParser` running outside Docker):

```
http://localhost:8002
redis://localhost:6379
http://localhost:11434/v1   # Ollama (NOT in compose; runs on host)
```

The compose file uses `host.docker.internal:11434` to let containers reach the host's Ollama (`OLLAMA_URL` for `intention-parser` and `catalog-normalizer`).

## Volumes — live code mounting

Three services mount repo modules at runtime so edits don't require image rebuilds:

```yaml
intention-parser:    ./IntentParser → /app/IntentParser
                     ./shared       → /app/shared
beckn-bap-client:    repo root is build context, COPYs ./shared at build time
catalog-normalizer:  ./CatalogNormalizer → /app/CatalogNormalizer
                     ./shared            → /app/shared
comparative-scoring: ./ComparativeScoring → /app/ComparativeScoring
```

`beckn-bap-client` is the exception — its `Dockerfile` is at `./services/beckn-bap-client/Dockerfile` and the build context is the repo root so it can `COPY ./shared`. Editing `services/beckn-bap-client/src/` requires a rebuild (`docker compose build beckn-bap-client`).

## Healthchecks gate startup

- `redis` healthcheck: `redis-cli ping` every 5 s, 5 retries.
- `beckn-bap-client` waits on `redis: service_healthy` AND `catalog-normalizer: service_started`.
- `onix-bap` and `onix-bpp` wait on `redis: service_healthy`.
- `sandbox-bpp` healthcheck: `wget -qO- http://localhost:3002/api/health`.

If `beckn-bap-client` crashes immediately, check Redis health: `docker compose ps`. Don't paper over with a sleep.

## Buyer billing — ENV-driven

`orchestrator` carries 8 `BUYER_*` env vars (`BUYER_NAME`, `BUYER_EMAIL`, `BUYER_PHONE`, address fields). They're read by `_build_billing_info()` in `services/orchestrator/src/workflow.py` and shipped as `participants[role=buyer]` in Beckn `/init`. Don't hardcode buyer info elsewhere — change the env defaults.

## ONIX routing config

`./config/` holds 6 YAML files mounted into `onix-bap` and `onix-bpp`:

- `generic-bap.yaml` — onix-bap server config
- `generic-bpp.yaml` — onix-bpp server config
- `generic-routing-BAPCaller.yaml` — outbound BAP routes (where `/discover` etc. go)
- `generic-routing-BAPReceiver.yaml` — inbound BAP routes (where `on_*` callbacks are sent)
- `generic-routing-BPPCaller.yaml`, `generic-routing-BPPReceiver.yaml` — same for BPP

**Routing trap**: ONIX appends the action name to the target. Target `http://host:8000/bpp` + action `discover` → `http://host:8000/bpp/discover`. Don't include the action name in the target URL inside these YAMLs.

## Common commands

```bash
docker compose up -d                              # whole stack
docker compose up -d redis onix-bap onix-bpp      # discovery infra only
docker compose logs -f beckn-bap-client           # tail one service
docker compose restart onix-bap                   # after editing config/*.yaml
docker compose build beckn-bap-client             # after editing services/beckn-bap-client/src/
docker compose down -v                            # stop + drop volumes (Redis cache wiped)
docker exec -it redis redis-cli                   # interactive Redis
docker compose ps                                 # health summary
```

## Frontend integration

The frontend (Next.js, `frontend/`) defaults to:
- `BAP_URL=http://localhost:8000`        (orchestrator)
- `INTENT_PARSER_URL=http://localhost:8000` (also orchestrator — proxies to 8001 internally)

Hence the orchestrator is published on **both** `8000` and `8004`. `8000` is the frontend-facing alias; `8004` is for direct testing. Both terminate at the same `aiohttp` app on container port `8004`.
