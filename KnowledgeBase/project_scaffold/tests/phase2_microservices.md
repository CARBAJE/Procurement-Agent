---
tags: [tests, phase-2, microservices, integration, docker, curl, pytest]
cssclasses: [procurement-doc, test-doc]
status: "#implemented"
related: ["[[phase2_core_intelligence_transaction_flow]]", "[[microservices_architecture]]", "[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[comparison_scoring_engine]]"]
---

# Tests — Phase 2: Arquitectura de Microservicios

> [!architecture] Contexto
> Los tests de Phase 2 verifican los 4 servicios bajo `services/` y el pipeline end-to-end vía el orquestador.
> Los tests de Phase 1 (`Bap-1/tests/`) siguen funcionando sin cambios — el monolito se preserva como referencia.

---

## 0 — Arrancar Docker

> [!warning] Prerequisito
> Ollama debe estar corriendo en el host con el modelo `qwen3:1.7b` cargado antes de levantar los servicios.
> ```bash
> ollama serve          # si no está ya corriendo
> ollama pull qwen3:1.7b
> ```

### Un solo comando levanta todo

Desde la raíz del repositorio (`Procurement-Agent/`):

```bash
docker compose up --build
```

Esto arranca **8 contenedores** en el orden correcto:

| Orden | Contenedor | Puerto | Rol |
|-------|-----------|--------|-----|
| 1 | `redis` | 6379 | Cache compartida para los adaptadores ONIX |
| 2 | `onix-bap` | 8081 | Adaptador BAP — firma ED25519, rutea discover/select |
| 2 | `onix-bpp` | 8082 | Adaptador BPP — recibe on_select, on_init, on_confirm |
| 2 | `sandbox-bpp` | 3002 | BPP mock — genera callbacks on_* |
| 3 | `intention-parser` | 8001 | Lambda 1 — parseo NL → BecknIntent |
| 3 | `comparative-scoring` | 8003 | Lambda 3 — selección por precio mínimo |
| 4 | `beckn-bap-client` | 8002 | Lambda 2 — discover, select, callbacks ONIX |
| 5 | `orchestrator` | 8004 | Step Functions local — orquesta Steps 1→2→3→4 |

> [!info] Configuración ONIX
> Los archivos `config/generic-routing-BAPCaller.yaml` y `config/generic-routing-BAPReceiver.yaml`
> en la raíz del repositorio configuran el ruteo del adaptador `onix-bap`:
> - **BAPCaller** → discover va a `beckn-bap-client:8002/bpp/discover` (catálogo local)
> - **BAPReceiver** → callbacks `on_*` van a `beckn-bap-client:8002/bap/receiver/{action}`

### Mapa de puertos local

```
HOST (macOS / Linux)                 DOCKER (beckn_network)
─────────────────────────────────────────────────────────────────────
localhost:8001 ──────────────────► intention-parser      :8001
localhost:8002 ──────────────────► beckn-bap-client      :8002
localhost:8003 ──────────────────► comparative-scoring   :8003
localhost:8004 ──────────────────► orchestrator          :8004
localhost:8081 ──────────────────► onix-bap              :8081
localhost:8082 ──────────────────► onix-bpp              :8082
localhost:3002 ──────────────────► sandbox-bpp           :3002
localhost:6379 ──────────────────► redis                 :6379
host.docker.internal:11434 ◄──── Ollama (proceso host)
```

**Flujo interno de discover** (todo dentro de `beckn_network`):

```
orchestrator:8004
  └─► beckn-bap-client:8002/discover       (Step 2)
        └─► onix-bap:8081/bap/caller/discover
              └─► beckn-bap-client:8002/bpp/discover   (catálogo local)
                    └─► localhost:8002/bap/receiver/on_discover  (self-callback)
                          └─► CallbackCollector → discover_async() retorna
  └─► comparative-scoring:8003/score       (Step 3)
  └─► beckn-bap-client:8002/select         (Step 4)
        └─► onix-bap:8081/bap/caller/select
              └─► onix-bpp:8082 → sandbox-bpp:3002
```

---

## 1 — Health checks (smoke test de arranque)

Verifican que cada servicio levantó correctamente. Deben retornar HTTP 200.

```bash
curl http://localhost:8001/health   # intention-parser
curl http://localhost:8002/health   # beckn-bap-client
curl http://localhost:8003/health   # comparative-scoring
curl http://localhost:8004/health   # orchestrator
```

**Respuestas esperadas:**

```json
// intention-parser
{ "status": "ok", "service": "intention-parser" }

// beckn-bap-client
{ "status": "ok", "service": "beckn-bap-client", "bap_id": "bap.example.com" }

// comparative-scoring
{ "status": "ok", "service": "comparative-scoring" }

// orchestrator
{
  "status": "ok",
  "service": "orchestrator",
  "upstream": {
    "intention_parser":    "http://intention-parser:8001",
    "beckn_bap_client":    "http://beckn-bap-client:8002",
    "comparative_scoring": "http://comparative-scoring:8003"
  }
}
```

---

## 2 — Tests por servicio

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
    "budget_constraints": null,
    "unit": "unit"
  },
  "routed_to": "qwen3:1.7b"
}
```

**Lo que se verifica:**
- `intent == "procurement"`
- `beckn_intent` no es `null`
- `quantity == 500`
- `delivery_timeline == 72` (3 días × 24h — no ISO 8601)
- `location_coordinates` contiene coordenadas decimales, no nombre de ciudad

#### `POST /parse` — query fuera de scope

```bash
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "¿cuál es la capital de Francia?"}' | jq .
```

**Respuesta esperada:**
```json
{
  "intent": "unknown",
  "confidence": 0.1,
  "beckn_intent": null,
  "routed_to": "qwen3:1.7b"
}
```

**Lo que se verifica:**
- `intent == "unknown"`
- `beckn_intent == null`

#### `POST /parse` — body vacío

```bash
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
```

**Respuesta esperada:** HTTP 400 — `"query is required"`

---

### Lambda 3 — `comparative-scoring` (puerto 8003)

> Se testea antes que el BAP client porque no depende de Docker ONIX.

#### `POST /score` — selecciona el más barato

```bash
curl -s -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{
    "offerings": [
      {
        "bpp_id": "bpp-1", "bpp_uri": "http://bpp1", "provider_id": "P1",
        "provider_name": "OfficeWorld", "item_id": "i1", "item_name": "A4 Paper",
        "price_value": "195.00", "price_currency": "INR"
      },
      {
        "bpp_id": "bpp-2", "bpp_uri": "http://bpp2", "provider_id": "P2",
        "provider_name": "PaperDirect", "item_id": "i2", "item_name": "A4 Ream",
        "price_value": "189.00", "price_currency": "INR"
      },
      {
        "bpp_id": "bpp-3", "bpp_uri": "http://bpp3", "provider_id": "P3",
        "provider_name": "StationeryHub", "item_id": "i3", "item_name": "A4 Premium",
        "price_value": "201.00", "price_currency": "INR"
      }
    ]
  }' | jq .
```

**Respuesta esperada:**
```json
{
  "selected": {
    "bpp_id": "bpp-2",
    "provider_name": "PaperDirect",
    "price_value": "189.00",
    "price_currency": "INR"
  }
}
```

**Lo que se verifica:**
- `selected.provider_name == "PaperDirect"` (el más barato de los 3)
- `selected.price_value == "189.00"`

#### `POST /score` — lista vacía

```bash
curl -s -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{"offerings": []}' | jq .
```

**Respuesta esperada:**
```json
{ "selected": null }
```

#### `POST /score` — precio inválido

```bash
curl -s -X POST http://localhost:8003/score \
  -H "Content-Type: application/json" \
  -d '{"offerings": [{"price_value": "N/A"}]}' | jq .
```

**Respuesta esperada:** HTTP 422 — error de precio no numérico

---

### Lambda 2 — `beckn-bap-client` (puerto 8002)

> Requiere Docker stack ONIX corriendo (`onix-bap` en puerto 8081).

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
  }' | jq .
```

**Respuesta esperada:**
```json
{
  "transaction_id": "<uuid>",
  "offerings": [
    {
      "bpp_id": "bpp.example.com",
      "provider_name": "OfficeWorld Supplies",
      "item_name": "A4 Paper 80gsm (500 sheets)",
      "price_value": "195.00",
      "price_currency": "INR"
    }
  ]
}
```

**Lo que se verifica:**
- `transaction_id` es un UUID válido
- `offerings` contiene ≥ 1 elemento
- Cada offering tiene `bpp_id`, `provider_name`, `price_value`

#### `POST /select` — confirmación de selección

```bash
curl -s -X POST http://localhost:8002/select \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "<uuid-del-discover>",
    "bpp_id": "bpp.example.com",
    "bpp_uri": "http://onix-bpp:8082/bpp/receiver",
    "item_id": "item-a4-ream",
    "item_name": "A4 Paper 80gsm Ream",
    "provider_id": "PROV-PAPERDIRECT-01",
    "price_value": "189.00",
    "price_currency": "INR",
    "quantity": 500
  }' | jq .
```

**Respuesta esperada:**
```json
{ "ack": "ACK" }
```

---

## 3 — Tests de compatibilidad con el frontend (Next.js)

> [!architecture] Cómo funciona la integración
> El frontend tiene dos pasos:
> - **Step 1** → `POST /parse` directo a `intention-parser:8001` → muestra preview al usuario
> - **Step 2** → `POST /discover` al `orchestrator:8004` con el `BecknIntent` confirmado → Steps 2→3→4
>
> El frontend llama directamente a `intention-parser` en Step 1 — el orquestador no interviene.

### Configuración del frontend para microservicios

`frontend/.env.local` ya está actualizado con los valores correctos:

```env
# Microservices architecture (Phase 2)
INTENT_PARSER_URL=http://localhost:8001   # intention-parser — POST /parse
BAP_URL=http://localhost:8004             # orchestrator — POST /discover (Steps 2→3→4)
```

- `POST /parse` → Next.js llama a `localhost:8001/parse` → `intention-parser` ✅
- `POST /discover` → Next.js llama a `localhost:8004/discover` → `orchestrator` (Steps 2→3→4) ✅

---

### Flujo completo frontend con microservicios

```bash
# Terminal 1: arrancar todos los microservicios (incluye ONIX stack)
docker compose up --build

# Terminal 2: arrancar el frontend
cd frontend && npm run dev
```

Abrir `http://localhost:3000` → login → ingresar query → confirmar intent → ver resultados.

**Verificaciones visuales:**
1. Step 1 (parse): preview del intent muestra `item`, `quantity`, `delivery_timeline` correctos
2. Step 2 (discover): grid de offerings visible con precios en INR
3. Offering seleccionado resaltado (el más barato)
4. `status: "live"` en la respuesta (no `"mock"`)

---
### Test A — Step 1: `/parse` (sin cambios de formato)

```bash
# Simula exactamente lo que hace el frontend en Step 1
curl -s -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "500 A4 paper Bangalore 3 days"}' | jq '{intent, beckn_intent}'
```

**Respuesta esperada:**
```json
{
  "intent": "procurement",
  "beckn_intent": {
    "item": "A4 paper",
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72,
    "unit": "unit"
  }
}
```

---

### Test B — Step 2: `POST /discover` en el orquestador (BecknIntent pre-parseado)

El frontend manda el `beckn_intent` confirmado por el usuario, **no la query raw**. El orquestador recibe el intent ya parseado y ejecuta los pasos 2→3→4 (discover → score → select).

```bash
# Simula exactamente lo que hace el frontend en Step 2
curl -s -X POST http://localhost:8004/discover \
  -H "Content-Type: application/json" \
  -d '{
    "item": "A4 paper",
    "descriptions": ["A4", "80gsm"],
    "quantity": 500,
    "location_coordinates": "12.9716,77.5946",
    "delivery_timeline": 72
  }' | jq '{transaction_id, status, selected: .selected.provider_name, offerings: (.offerings | length)}'
```

**Respuesta esperada** (mismo formato que el monolito):
```json
{
  "transaction_id": "<uuid>",
  "status": "live",
  "selected": "PaperDirect",
  "offerings": 3
}
```

**Lo que se verifica:**
- `status == "live"` (no `"mock"`)
- `selected` no es `null`
- `offerings` tiene ≥ 1 elemento
- La respuesta tiene los mismos campos que el monolito: `transaction_id`, `offerings`, `selected`, `messages`, `status`
