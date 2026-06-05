---
tags: [tests, phase-2, microservices, integration, docker, curl, pytest, persistence]
cssclasses: [procurement-doc, test-doc]
status: "#implemented"
related: ["[[phase2_core_intelligence_transaction_flow]]", "[[microservices_architecture]]", "[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]", "[[catalog_normalizer]]", "[[data_normalizer]]"]
---

# Tests — Phase 2: Arquitectura de Microservicios

> [!architecture] Contexto
> Los tests de Phase 2 verifican los **6 servicios** bajo `services/` y el pipeline end-to-end vía el orquestador, incluyendo la persistencia en PostgreSQL a través del Data Normalizer.
> Los tests de Phase 1 (`Bap-1/tests/`) siguen funcionando sin cambios — el monolito se preserva como referencia.

---

## 0 — Prerequisitos

> [!warning] Antes de levantar Docker
> Asegurarse de que los siguientes procesos del host están corriendo:

```bash
# 1. Ollama — requerido por intention-parser y catalog-normalizer
ollama serve
ollama pull qwen3:1.7b

# 2. PostgreSQL — requerido por data-normalizer
# Verificar que está corriendo y que la base de datos existe
psql -U cristiamontiel -c "\l" | grep procurement_agent
# Si no existe: createdb procurement_agent
# Aplicar el schema si es la primera vez:
# psql procurement_agent < database/sql/00_extensions_and_types.sql
# psql procurement_agent < database/sql/01_users.sql
# ... (hasta 17_indexes.sql)
```

---

## 1 — Arrancar Docker

### Un solo comando levanta todo

Desde la raíz del repositorio (`Procurement-Agent/`):

```bash
docker compose up --build
```

Esto arranca **10 contenedores** en el orden correcto:

| Orden | Contenedor | Puerto | Rol |
|-------|-----------|--------|-----|
| 1 | `redis` | 6379 | Cache compartida para los adaptadores ONIX |
| 2 | `onix-bap` | 8081 | Adaptador BAP — firma ED25519, rutea discover/select |
| 2 | `onix-bpp` | 8082 | Adaptador BPP — recibe on_select, on_init, on_confirm |
| 2 | `sandbox-bpp` | 3002 | BPP mock — genera callbacks on_* |
| 3 | `catalog-normalizer` | 8005 | Lambda 4 — normalización de formatos de catálogo |
| 3 | `intention-parser` | 8001 | Lambda 1 — parseo NL → BecknIntent |
| 3 | `comparative-scoring` | 8003 | Lambda 3 — selección por precio mínimo |
| 4 | `beckn-bap-client` | 8002 | Lambda 2 — discover, select, init, confirm, callbacks |
| 5 | `data-normalizer` | 8006 | Lambda 5 — persistencia PostgreSQL |
| 6 | `orchestrator` | 8004 | Step Functions local — orquesta todo el pipeline |

> [!info] Configuración ONIX
> Los archivos `config/generic-routing-BAPCaller.yaml` y `config/generic-routing-BAPReceiver.yaml`
> configuran el ruteo del adaptador `onix-bap`:
> - **BAPCaller** → discover va a `beckn-bap-client:8002/bpp/discover` (catálogo local)
> - **BAPReceiver** → callbacks `on_*` van a `beckn-bap-client:8002/bap/receiver/{action}`

### Mapa de puertos completo

```
HOST (macOS / Linux)                 DOCKER (beckn_network)
─────────────────────────────────────────────────────────────────────────
localhost:8001 ──────────────────► intention-parser      :8001  (Lambda 1)
localhost:8002 ──────────────────► beckn-bap-client      :8002  (Lambda 2)
localhost:8003 ──────────────────► comparative-scoring   :8003  (Lambda 3)
localhost:8004 ──────────────────► orchestrator          :8004  (Step Functions)
localhost:8005 ──────────────────► catalog-normalizer    :8005  (Lambda 4)
localhost:8006 ──────────────────► data-normalizer       :8006  (Lambda 5)
localhost:8081 ──────────────────► onix-bap              :8081  (BAP ONIX adapter)
localhost:8082 ──────────────────► onix-bpp              :8082  (BPP ONIX adapter)
localhost:3002 ──────────────────► sandbox-bpp           :3002  (BPP mock)
localhost:6379 ──────────────────► redis                 :6379  (ONIX cache)
host.docker.internal:11434 ◄──── Ollama      (proceso del host)
host.docker.internal:5432  ◄──── PostgreSQL  (proceso del host)
```

**Flujo interno del pipeline completo** (dentro de `beckn_network`):

```
orchestrator:8004
  ├─► data-normalizer:8006/normalize/request    (persiste request)
  ├─► intention-parser:8001/parse               (Step 1)
  ├─► data-normalizer:8006/normalize/intent     (persiste intent)
  ├─► beckn-bap-client:8002/discover            (Step 2)
  │     └─► onix-bap:8081 → beckn-bap-client:8002/bpp/discover
  │           └─► catalog-normalizer:8005/normalize  (normaliza formatos)
  │           └─► self-callback on_discover → CallbackCollector
  ├─► data-normalizer:8006/normalize/discovery  (persiste offerings)
  ├─► comparative-scoring:8003/score            (Step 3)
  ├─► data-normalizer:8006/normalize/scoring    (persiste scores)
  ├─► beckn-bap-client:8002/select             (Step 4a)
  ├─► beckn-bap-client:8002/init               (Step 4b)
  ├─► beckn-bap-client:8002/confirm            (Step 4c)
  └─► data-normalizer:8006/normalize/order     (persiste PO)
```

---

## 2 — Health Checks (smoke test de arranque)

Verifican que todos los servicios levantaron correctamente. Ejecutar en orden.

```bash
# Servicios de negocio
curl -s http://localhost:8001/health | jq .   # intention-parser
curl -s http://localhost:8002/health | jq .   # beckn-bap-client
curl -s http://localhost:8003/health | jq .   # comparative-scoring
curl -s http://localhost:8004/health | jq .   # orchestrator
curl -s http://localhost:8005/health | jq .   # catalog-normalizer
curl -s http://localhost:8006/health | jq .   # data-normalizer
```

**Respuestas esperadas:**

```json
// :8001
{ "status": "ok", "service": "intention-parser" }

// :8002
{ "status": "ok", "service": "beckn-bap-client", "bap_id": "bap.example.com" }

// :8003
{ "status": "ok", "service": "comparative-scoring" }

// :8004
{
  "status": "ok",
  "service": "orchestrator",
  "upstream": {
    "intention_parser":    "http://intention-parser:8001",
    "beckn_bap_client":    "http://beckn-bap-client:8002",
    "comparative_scoring": "http://comparative-scoring:8003"
  }
}

// :8005
{ "status": "ok", "service": "catalog-normalizer" }

// :8006
{ "status": "ok", "service": "data-normalizer" }
```

---

## 3 — Tests por servicio

### Lambda 1 — `intention-parser` (puerto 8001)

#### `POST /parse` — query de aprovisionamiento válida

```bash
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "500 A4 paper Bangalore 3 days"}' | jq .
```

**Respuesta esperada:**
```json
{
  "intent": "procurement",
  "confidence": 0.95,
  "beckn_intent": {
    "item": "A4 paper",
    "descriptions": ["A4"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72,
    "budget_constraints": null
  },
  "routed_to": "qwen3:1.7b"
}
```

**Lo que se verifica:**
- `intent == "procurement"`
- `quantity == 500`
- `delivery_timeline == 72` (3 días × 24h — no ISO 8601)
- `location_coordinates` contiene coordenadas decimales, no nombre de ciudad

#### `POST /parse` — query fuera de scope

```bash
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "¿cuál es la capital de Francia?"}' | jq '{intent, beckn_intent}'
```

**Respuesta esperada:**
```json
{ "intent": "unknown", "beckn_intent": null }
```

#### `POST /parse` — body vacío

```bash
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
```

**Respuesta esperada:** HTTP 400

---

### Lambda 3 — `comparative-scoring` (puerto 8003)

> Se testea antes que el BAP client porque no depende de Docker ONIX.

#### `POST /score` — selecciona el más barato

```bash
curl -s -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{
    "offerings": [
      {"bpp_id":"bpp-1","bpp_uri":"http://bpp1","provider_id":"P1","provider_name":"OfficeWorld",
       "item_id":"i1","item_name":"A4 Paper","price_value":"195.00","price_currency":"INR"},
      {"bpp_id":"bpp-2","bpp_uri":"http://bpp2","provider_id":"P2","provider_name":"PaperDirect",
       "item_id":"i2","item_name":"A4 Ream","price_value":"168.00","price_currency":"INR"},
      {"bpp_id":"bpp-3","bpp_uri":"http://bpp3","provider_id":"P3","provider_name":"StationeryHub",
       "item_id":"i3","item_name":"A4 Premium","price_value":"201.00","price_currency":"INR"}
    ]
  }' | jq '{selected: .selected.provider_name, price: .selected.price_value}'
```

**Respuesta esperada:**
```json
{ "selected": "PaperDirect", "price": "168.00" }
```

#### `POST /score` — lista vacía → selected null

```bash
curl -s -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{"offerings": []}' | jq .
```

**Respuesta esperada:** `{ "selected": null }`

#### `POST /score` — precio no numérico → HTTP 422

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{"offerings": [{"price_value": "N/A"}]}'
# Esperado: 422
```

---

### Lambda 2 — `beckn-bap-client` (puerto 8002)

> Requiere stack ONIX corriendo (`onix-bap` en puerto 8081).

#### `POST /discover` — descubrimiento Beckn

```bash
curl -s -X POST http://localhost:8002/discover \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["A4", "80gsm"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }' | jq '{transaction_id, offering_count: (.offerings | length)}'
```

**Respuesta esperada:**
```json
{ "transaction_id": "<uuid>", "offering_count": 6 }
```

**Lo que se verifica:**
- `transaction_id` es un UUID válido
- `offerings` contiene ≥ 1 elemento con `bpp_id`, `provider_name`, `price_value`

#### `POST /select` → `POST /init` → `POST /confirm` — ciclo transaccional completo

```bash
# 1. Discover → obtener transaction_id y offering
RESP=$(curl -s -X POST http://localhost:8002/discover \
  -H "Content-Type: application/json" \
  -d '{"item":"A4 paper","quantity":500,"location_coordinates":"12.97,77.59","delivery_timeline":72}')

TXN=$(echo $RESP | jq -r '.transaction_id')
BPP_ID=$(echo $RESP | jq -r '.offerings[0].bpp_id')
BPP_URI=$(echo $RESP | jq -r '.offerings[0].bpp_uri')
ITEM_ID=$(echo $RESP | jq -r '.offerings[0].item_id')
ITEM_NAME=$(echo $RESP | jq -r '.offerings[0].item_name')
PROV_ID=$(echo $RESP | jq -r '.offerings[0].provider_id')
PRICE=$(echo $RESP | jq -r '.offerings[0].price_value')

# 2. Select
curl -s -X POST http://localhost:8002/select \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN\",\"bpp_id\":\"$BPP_ID\",\"bpp_uri\":\"$BPP_URI\",
      \"item_id\":\"$ITEM_ID\",\"item_name\":\"$ITEM_NAME\",\"provider_id\":\"$PROV_ID\",
      \"price_value\":\"$PRICE\",\"price_currency\":\"INR\",\"quantity\":500}" | jq .
# Esperado: { "ack": "ACK" }

# 3. Init
CONTRACT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
curl -s -X POST http://localhost:8002/init \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN\",\"contract_id\":\"$CONTRACT_ID\",
      \"bpp_id\":\"$BPP_ID\",\"bpp_uri\":\"$BPP_URI\",
      \"items\":[{\"id\":\"$ITEM_ID\",\"quantity\":500,\"name\":\"$ITEM_NAME\",
                  \"price_value\":\"$PRICE\",\"price_currency\":\"INR\"}]}" | jq .
# Esperado: { "ack": "ACK", "payment_terms": {...} }

# 4. Confirm
curl -s -X POST http://localhost:8002/confirm \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN\",\"contract_id\":\"$CONTRACT_ID\",
      \"bpp_id\":\"$BPP_ID\",\"bpp_uri\":\"$BPP_URI\",
      \"items\":[{\"id\":\"$ITEM_ID\",\"quantity\":500,\"name\":\"$ITEM_NAME\",
                  \"price_value\":\"$PRICE\",\"price_currency\":\"INR\"}],
      \"payment_terms\":{\"type\":\"ON_FULFILLMENT\",\"collected_by\":\"BPP\",
                         \"currency\":\"INR\",\"status\":\"NOT-PAID\"}}" | jq '{order_id, order_state}'
# Esperado: { "order_id": "<uuid>", "order_state": "CREATED" }
```

---

### Lambda 4 — `catalog-normalizer` (puerto 8005)

> No depende de ONIX. Acepta cualquier formato de catálogo BPP y lo normaliza.

#### `POST /normalize` — Formato A (`resources[]`)

```bash
curl -s -X POST http://localhost:8005/normalize \
  -H "Content-Type: application/json" \
  -d '{
    "catalog": {
      "resources": [
        {
          "id": "item-a4-001",
          "descriptor": { "name": "A4 Paper 80gsm" },
          "provider": { "id": "prov-1", "descriptor": { "name": "OfficeWorld" } },
          "price": { "value": 195.0, "currency": "INR" },
          "rating": { "ratingValue": "4.8" }
        }
      ]
    },
    "bpp_id": "bpp.test.com",
    "bpp_uri": "http://bpp.test.com/receiver"
  }' | jq '{format_variant, count: (.offerings | length), item: .offerings[0].item_name}'
```

**Respuesta esperada:**
```json
{ "format_variant": 1, "count": 1, "item": "A4 Paper 80gsm" }
```

#### `POST /normalize` — Formato B (`providers[].items[]`)

```bash
curl -s -X POST http://localhost:8005/normalize \
  -H "Content-Type: application/json" \
  -d '{
    "catalog": {
      "providers": [
        {
          "id": "prov-2",
          "descriptor": { "name": "PaperDirect" },
          "rating": "4.5",
          "items": [
            {
              "id": "item-a4-002",
              "descriptor": { "name": "A4 Ream 500 sheets" },
              "price": { "value": 168.0, "currency": "INR" }
            }
          ]
        }
      ]
    },
    "bpp_id": "bpp.test2.com",
    "bpp_uri": "http://bpp.test2.com/receiver"
  }' | jq '{format_variant, provider: .offerings[0].provider_name, rating: .offerings[0].rating}'
```

**Respuesta esperada:**
```json
{ "format_variant": 2, "provider": "PaperDirect", "rating": "4.5" }
```

**Lo que se verifica:**
- `format_variant` identifica el formato correctamente
- El `rating` se toma del proveedor (nivel padre), no del item
- Los campos `bpp_id` y `bpp_uri` son inyectados por el normalizador

---

### Lambda 5 — `data-normalizer` (puerto 8006)

> Requiere PostgreSQL corriendo en el host. Todos estos tests persisten datos reales.

#### `POST /normalize/request` — crea raíz del pipeline

```bash
curl -s -X POST http://localhost:8006/normalize/request \
  -H "Content-Type: application/json" \
  -d '{"raw_input_text": "500 reams A4 paper Bangalore 3 days", "channel": "web"}' | jq .
```

**Respuesta esperada:** HTTP 201
```json
{ "request_id": "<uuid>" }
```

**Verificar en PostgreSQL:**
```sql
SELECT request_id, raw_input_text, status, created_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 1;
-- status debe ser 'draft'
```

#### `PATCH /normalize/status` — ciclo de vida del request

```bash
REQUEST_ID="<uuid-del-paso-anterior>"

# draft → parsing
curl -s -X PATCH http://localhost:8006/normalize/status \
  -H "Content-Type: application/json" \
  -d "{\"request_id\":\"$REQUEST_ID\",\"status\":\"parsing\"}" | jq .

# parsing → discovering
curl -s -X PATCH http://localhost:8006/normalize/status \
  -H "Content-Type: application/json" \
  -d "{\"request_id\":\"$REQUEST_ID\",\"status\":\"discovering\"}" | jq .
```

**Verificar en PostgreSQL:**
```sql
SELECT status FROM procurement_requests WHERE request_id = '<uuid>';
-- Debe mostrar 'discovering'
```

#### `POST /normalize/intent` — persiste parsed_intents + beckn_intents

```bash
curl -s -X POST http://localhost:8006/normalize/intent \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\": \"$REQUEST_ID\",
    \"intent_class\": \"procurement\",
    \"confidence\": 0.97,
    \"model_version\": \"qwen3:1.7b\",
    \"beckn_intent\": {
      \"item\": \"A4 paper\",
      \"descriptions\": [\"80gsm\", \"A4\"],
      \"quantity\": 500,
      \"location_coordinates\": \"12.9716,77.5946\",
      \"delivery_timeline\": 72
    }
  }" | jq .
```

**Respuesta esperada:** HTTP 201
```json
{ "intent_id": "<uuid>", "beckn_intent_id": "<uuid>" }
```

**Verificar en PostgreSQL:**
```sql
SELECT pi.intent_class, pi.confidence_score,
       bi.item, bi.quantity, bi.delivery_timeline_hours, bi.location_coordinates
FROM parsed_intents pi
JOIN beckn_intents bi ON bi.intent_id = pi.intent_id
ORDER BY pi.parsed_at DESC LIMIT 1;
-- delivery_timeline_hours debe ser 72
-- location_coordinates debe ser '12.9716,77.5946'
```

#### `POST /normalize/discovery` — persiste discovery_queries + seller_offerings + bpp

```bash
BECKN_INTENT_ID="<uuid-del-paso-anterior>"

curl -s -X POST http://localhost:8006/normalize/discovery \
  -H "Content-Type: application/json" \
  -d "{
    \"beckn_intent_id\": \"$BECKN_INTENT_ID\",
    \"network_id\": \"beckn-default\",
    \"offerings\": [
      {
        \"bpp_id\": \"bpp.example.com\",
        \"bpp_uri\": \"http://onix-bpp:8082/bpp/receiver\",
        \"provider_id\": \"PROV-PAPERDIRECT-01\",
        \"provider_name\": \"PaperDirect India\",
        \"item_id\": \"item-a4-paperdirect\",
        \"item_name\": \"A4 Paper 80gsm Ream\",
        \"price_value\": \"168.00\",
        \"price_currency\": \"INR\",
        \"available_quantity\": 5000,
        \"rating\": \"4.2\",
        \"specifications\": [\"Brightness 92\", \"Recycled 30%\"],
        \"fulfillment_hours\": 48
      },
      {
        \"bpp_id\": \"bpp.example.com\",
        \"bpp_uri\": \"http://onix-bpp:8082/bpp/receiver\",
        \"provider_id\": \"PROV-OFFICEWORLD-01\",
        \"provider_name\": \"OfficeWorld Supplies\",
        \"item_id\": \"item-a4-officeworld\",
        \"item_name\": \"A4 Paper 80gsm (500 sheets)\",
        \"price_value\": \"195.00\",
        \"price_currency\": \"INR\",
        \"available_quantity\": 1000,
        \"rating\": \"4.8\",
        \"specifications\": [\"Brightness 96\", \"FSC Certified\"],
        \"fulfillment_hours\": 24
      }
    ]
  }" | jq .
```

**Respuesta esperada:** HTTP 201
```json
{
  "query_id": "<uuid>",
  "offering_ids": [
    { "item_id": "item-a4-paperdirect", "offering_id": "<uuid>" },
    { "item_id": "item-a4-officeworld", "offering_id": "<uuid>" }
  ]
}
```

**Verificar en PostgreSQL:**
```sql
-- Verificar offerings persistidos con conversión de tipos correcta
SELECT so.item_id, so.price, so.delivery_eta_hours, so.quality_rating,
       b.name AS bpp_name, b.endpoint_url
FROM seller_offerings so
JOIN bpp b ON b.bpp_id = so.bpp_id
ORDER BY so.received_at DESC LIMIT 5;
-- price debe ser DECIMAL (168.00, 195.00) — NO string
-- delivery_eta_hours debe ser INTEGER (48, 24)
-- quality_rating debe ser FLOAT (4.2, 4.8) — NO string
```

#### `POST /normalize/scoring` — persiste scored_offers con transformación 0→100

```bash
QUERY_ID="<uuid-del-paso-anterior>"
OFFERING_ID_1="<offering_id de item-a4-paperdirect>"
OFFERING_ID_2="<offering_id de item-a4-officeworld>"

curl -s -X POST http://localhost:8006/normalize/scoring \
  -H "Content-Type: application/json" \
  -d "{
    \"query_id\": \"$QUERY_ID\",
    \"scores\": [
      {
        \"offering_id\": \"$OFFERING_ID_1\",
        \"rank\": 1,
        \"composite_score\": 1.0,
        \"price_value\": \"168.00\"
      },
      {
        \"offering_id\": \"$OFFERING_ID_2\",
        \"rank\": 2,
        \"composite_score\": 0.0,
        \"price_value\": \"195.00\"
      }
    ]
  }" | jq .
```

**Respuesta esperada:** HTTP 201
```json
{
  "score_ids": [
    { "offering_id": "<uuid>", "score_id": "<uuid>" },
    { "offering_id": "<uuid>", "score_id": "<uuid>" }
  ]
}
```

**Verificar en PostgreSQL:**
```sql
SELECT rank, total_score, tco_value
FROM scored_offers
ORDER BY scored_at DESC LIMIT 2;
-- total_score para composite_score=1.0 debe ser 100.0
-- total_score para composite_score=0.0 debe ser 0.0
-- tco_value = precio como FLOAT (168.0, 195.0)
```

#### `POST /normalize/order` — cadena FK completa (3 tablas en 1 transacción)

```bash
SCORE_ID_1="<score_id del offering más barato>"

curl -s -X POST http://localhost:8006/normalize/order \
  -H "Content-Type: application/json" \
  -d "{
    \"score_id\": \"$SCORE_ID_1\",
    \"bpp_uri\": \"http://onix-bpp:8082/bpp/receiver\",
    \"item_id\": \"item-a4-paperdirect\",
    \"quantity\": 500,
    \"agreed_price\": 168.00,
    \"beckn_confirm_ref\": \"order-test-$(date +%s)\",
    \"delivery_terms\": \"Standard delivery\",
    \"currency\": \"INR\"
  }" | jq .
```

**Respuesta esperada:** HTTP 201
```json
{ "po_id": "<uuid>" }
```

**Verificar la cadena FK completa en PostgreSQL:**
```sql
SELECT po.po_id, po.agreed_price, po.quantity, po.status AS po_status,
       ad.status AS approval_status, ad.approval_level,
       no2.strategy_applied, no2.acceptance_status
FROM purchase_orders po
JOIN approval_decisions ad ON ad.approval_id = po.approval_id
JOIN negotiation_outcomes no2 ON no2.negotiation_id = ad.negotiation_id
ORDER BY po.created_at DESC LIMIT 1;
-- po_status            = 'pending'
-- approval_status      = 'auto_approved'
-- approval_level       = 'auto'
-- strategy_applied     = 'skipped'
-- acceptance_status    = 'skipped'
```

---

## 4 — Tests de integración vía orchestrator

### `POST /run` — pipeline completo NL (Steps 1→2→3→4)

```bash
curl -s -X POST http://localhost:8004/run \
  -H "Content-Type: application/json" \
  -d '{"query": "500 A4 paper Bangalore 3 days"}' | \
  jq '{transaction_id, status, selected: .selected.provider_name, msg_count: (.messages | length)}'
```

**Respuesta esperada:**
```json
{
  "transaction_id": "<uuid>",
  "status": "live",
  "selected": "<provider más barato>",
  "msg_count": 4
}
```

**Verificar persistencia automática en PostgreSQL:**
```sql
-- Dentro de los 5 segundos posteriores al request
SELECT raw_input_text, status FROM procurement_requests ORDER BY created_at DESC LIMIT 1;
-- status debe ser 'negotiating' (el orquestador llega hasta scoring)
```

---

### `POST /compare` — discover + score (flujo frontend principal)

```bash
COMPARE_RESP=$(curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["80gsm"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }')

echo $COMPARE_RESP | jq '{
  transaction_id,
  status,
  offering_count: (.offerings | length),
  recommended: .recommended_item_id,
  scoring_criteria: (.scoring.criteria | length)
}'
```

**Respuesta esperada:**
```json
{
  "transaction_id": "<uuid>",
  "status": "live",
  "offering_count": 6,
  "recommended": "<item_id del más barato>",
  "scoring_criteria": 1
}
```

**Guardar transaction_id para el commit:**
```bash
TXN_ID=$(echo $COMPARE_RESP | jq -r '.transaction_id')
RECOMMENDED_ID=$(echo $COMPARE_RESP | jq -r '.recommended_item_id')
echo "TXN_ID=$TXN_ID  RECOMMENDED_ID=$RECOMMENDED_ID"
```

**Lo que se verifica:**
- `status == "live"` (no `"mock"` — requiere Docker stack activo)
- `offerings` tiene ≥ 1 elemento
- `recommended_item_id` no es `null`
- `scoring.criteria` tiene la dimensión de precio

**Verificar persistencia en PostgreSQL:**
```sql
SELECT raw_input_text, status FROM procurement_requests ORDER BY created_at DESC LIMIT 1;
-- status = 'negotiating' (después de scoring)
SELECT COUNT(*) FROM seller_offerings WHERE received_at > NOW() - INTERVAL '1 minute';
-- debe retornar el número de offerings (6 en el catálogo local)
SELECT rank, total_score FROM scored_offers ORDER BY scored_at DESC LIMIT 6;
-- debe haber 6 scored_offers, scores entre 0 y 100
```

---

### `POST /commit` — select + init + confirm (cierra el ciclo)

```bash
# Usar el TXN_ID y RECOMMENDED_ID del compare anterior
curl -s -X POST http://localhost:8004/commit \
  -H "Content-Type: application/json" \
  -d "{
    \"transaction_id\": \"$TXN_ID\",
    \"chosen_item_id\": \"$RECOMMENDED_ID\"
  }" | jq '{transaction_id, order_id, order_state, status}'
```

**Respuesta esperada:**
```json
{
  "transaction_id": "<uuid>",
  "order_id": "<order_id>",
  "order_state": "CREATED",
  "status": "live"
}
```

**Verificar Purchase Order en PostgreSQL:**
```sql
SELECT po.po_id, po.item_id, po.quantity, po.agreed_price,
       po.beckn_confirm_ref, po.status AS po_status
FROM purchase_orders po
ORDER BY po.created_at DESC LIMIT 1;
-- beckn_confirm_ref = order_id retornado por /commit
-- agreed_price = precio del offering elegido
-- po_status = 'pending'
```

---

### `GET /status/{txn_id}/{order_id}` — seguimiento de orden

```bash
ORDER_ID="<order_id del commit anterior>"

curl -s "http://localhost:8004/status/$TXN_ID/$ORDER_ID" | \
  jq '{state, observed_at, status}'
```

**Respuesta esperada:**
```json
{
  "state": "CREATED",
  "observed_at": "<iso8601>",
  "status": "live"
}
```

---

## 5 — Tests de compatibilidad con el frontend (Next.js)

> [!architecture] Cómo funciona la integración con el frontend
> El frontend tiene **tres puntos de integración** con los microservicios:
> - **Step 1** → `POST /parse` directo a `intention-parser:8001` — el usuario ve el intent preview
> - **Step 2** → `POST /compare` al `orchestrator:8004` con el BecknIntent confirmado — el usuario ve offerings rankeados
> - **Step 3** → `POST /commit` al `orchestrator:8004` con el chosen_item_id — el usuario confirma la orden

### Configuración del frontend para microservicios

`frontend/.env.local`:

```env
INTENT_PARSER_URL=http://localhost:8001   # intention-parser — POST /parse
BAP_URL=http://localhost:8004             # orchestrator — POST /compare, /commit, /status
```

### Test A — Step 1 del frontend: `POST /parse`

```bash
# Simula exactamente lo que hace el frontend en Step 1
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "500 A4 paper Bangalore 3 days"}' | \
  jq '{intent, beckn_intent: {item: .beckn_intent.item, quantity: .beckn_intent.quantity,
       delivery_timeline: .beckn_intent.delivery_timeline}}'
```

**Respuesta esperada:**
```json
{
  "intent": "procurement",
  "beckn_intent": { "item": "A4 paper", "quantity": 500, "delivery_timeline": 72 }
}
```

**Criterio de aceptación UI:**
- El preview del intent muestra `A4 paper × 500 | 72h`
- El botón "Confirmar" se habilita

---

### Test B — Step 2 del frontend: `POST /compare`

```bash
# Simula lo que hace el frontend en Step 2 tras confirmar el intent
curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["80gsm"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }' | jq '{
    transaction_id,
    status,
    offering_count: (.offerings | length),
    recommended: .recommended_item_id,
    top_provider: .offerings[0].provider_name,
    reasoning_steps: (.reasoning_steps | length)
  }'
```

**Respuesta esperada:**
```json
{
  "transaction_id": "<uuid>",
  "status": "live",
  "offering_count": 6,
  "recommended": "<item_id>",
  "top_provider": "<provider_name>",
  "reasoning_steps": 2
}
```

**Criterio de aceptación UI:**
- El grid de offerings muestra las 6 tarjetas
- La oferta recomendada aparece resaltada
- Los `reasoning_steps` se despliegan en el panel de transparencia del agente
- `status == "live"` (no `"mock"`)

---

### Test C — Step 3 del frontend: `POST /commit`

```bash
# Simula al usuario eligiendo la oferta recomendada
TXN_ID="<transaction_id del test B>"
CHOSEN_ID="<recommended_item_id del test B>"

curl -s -X POST http://localhost:8004/commit \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN_ID\",\"chosen_item_id\":\"$CHOSEN_ID\"}" | \
  jq '{order_id, order_state, status, reasoning_count: (.reasoning_steps | length)}'
```

**Respuesta esperada:**
```json
{
  "order_id": "<order_id>",
  "order_state": "CREATED",
  "status": "live",
  "reasoning_count": 4
}
```

**Criterio de aceptación UI:**
- La pantalla de confirmación muestra `order_id` y `order_state`
- Los `reasoning_steps` (send_select → send_init → send_confirm → present_results) se muestran en el panel de trazabilidad
- `status == "live"` indica flujo real, no mock

---

### Test D — Seguimiento de orden desde el frontend: `GET /status/{txn}/{order}`

```bash
ORDER_ID="<order_id del test C>"
curl -s "http://localhost:8004/status/$TXN_ID/$ORDER_ID" | \
  jq '{state, observed_at, status}'
```

**Criterio de aceptación UI:**
- La pantalla de tracking actualiza el estado cada ~30 segundos
- `state` pasa de `CREATED` → `ACCEPTED` → `IN-FULFILLMENT` → `COMPLETE` conforme avanza la orden en el sandbox-bpp

---

### Test E — Verificación de persistencia completa post-flujo frontend

Después de completar los Tests A → D, verificar que todo quedó guardado en PostgreSQL:

```sql
-- 1. Request creado con status final
SELECT raw_input_text, status, updated_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 1;
-- status = 'confirmed' (si el data-normalizer pudo persistir el order)

-- 2. Intent y BecknIntent persistidos
SELECT pi.intent_class, pi.confidence_score, bi.item, bi.quantity
FROM parsed_intents pi
JOIN beckn_intents bi ON bi.intent_id = pi.intent_id
ORDER BY pi.parsed_at DESC LIMIT 1;

-- 3. Offerings y scores persistidos
SELECT so.item_id, so.price, sc.rank, sc.total_score
FROM seller_offerings so
JOIN scored_offers sc ON sc.offering_id = so.offering_id
ORDER BY sc.rank ASC LIMIT 6;

-- 4. Purchase Order creado con cadena FK completa
SELECT po.po_id, po.agreed_price, po.beckn_confirm_ref,
       ad.status AS approval_status
FROM purchase_orders po
JOIN approval_decisions ad ON ad.approval_id = po.approval_id
ORDER BY po.created_at DESC LIMIT 1;
```

---

## 6 — Test de resiliencia: Data Normalizer caído

> Verifica que el pipeline sigue funcionando si la base de datos o el data-normalizer no están disponibles.

```bash
# 1. Detener el data-normalizer
docker stop procurement-agent-data-normalizer-1

# 2. Ejecutar el pipeline completo igual que antes
curl -s -X POST http://localhost:8004/compare \
  -H "Content-Type: application/json" \
  -d '{"item":"A4 paper","quantity":500,"location_coordinates":"12.97,77.59","delivery_timeline":72}' | \
  jq '{status, offering_count: (.offerings | length)}'

# Respuesta esperada: status="live", offering_count=6
# El pipeline devuelve resultados correctos — la persistencia falla silenciosamente (DEBUG log)

# 3. Restaurar el data-normalizer
docker start procurement-agent-data-normalizer-1
```

**Lo que se verifica:**
- El orquestador devuelve HTTP 200 con offerings aunque el data-normalizer esté caído
- Los logs del orquestador muestran `[data-normalizer] /normalize/request skipped: ...` en nivel DEBUG
- Después de restaurar el servicio, nuevas peticiones vuelven a persistir normalmente

---

## 7 — Flujo completo (script de un solo comando)

```bash
#!/bin/bash
# Script de verificación end-to-end — ejecutar con Docker stack activo

BASE="http://localhost:8004"

echo "=== COMPARE ==="
COMPARE=$(curl -s -X POST $BASE/compare \
  -H "Content-Type: application/json" \
  -d '{"item":"A4 paper","descriptions":["80gsm"],"quantity":500,
       "location_coordinates":"12.97,77.59","delivery_timeline":72}')

TXN=$(echo $COMPARE | jq -r '.transaction_id')
STATUS=$(echo $COMPARE | jq -r '.status')
COUNT=$(echo $COMPARE | jq '.offerings | length')
RECOMMENDED=$(echo $COMPARE | jq -r '.recommended_item_id')

echo "txn=$TXN status=$STATUS offerings=$COUNT recommended=$RECOMMENDED"

echo ""
echo "=== COMMIT ==="
COMMIT=$(curl -s -X POST $BASE/commit \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN\",\"chosen_item_id\":\"$RECOMMENDED\"}")

ORDER_ID=$(echo $COMMIT | jq -r '.order_id')
ORDER_STATE=$(echo $COMMIT | jq -r '.order_state')
COMMIT_STATUS=$(echo $COMMIT | jq -r '.status')

echo "order_id=$ORDER_ID state=$ORDER_STATE status=$COMMIT_STATUS"

echo ""
echo "=== STATUS ==="
curl -s "$BASE/status/$TXN/$ORDER_ID" | jq '{state, status}'

echo ""
echo "=== PostgreSQL ==="
psql procurement_agent -c "
  SELECT po.po_id, po.agreed_price, po.beckn_confirm_ref, ad.status
  FROM purchase_orders po
  JOIN approval_decisions ad ON ad.approval_id = po.approval_id
  ORDER BY po.created_at DESC LIMIT 1;"
```

**Salida esperada:**
```
=== COMPARE ===
txn=<uuid> status=live offerings=6 recommended=item-a4-budgetpaper

=== COMMIT ===
order_id=<order_id> state=CREATED status=live

=== STATUS ===
{ "state": "CREATED", "status": "live" }

=== PostgreSQL ===
 po_id | agreed_price | beckn_confirm_ref | status
-------+--------------+------------------+-------
 <uuid>|       165.00 | <order_id>        | auto_approved
```
