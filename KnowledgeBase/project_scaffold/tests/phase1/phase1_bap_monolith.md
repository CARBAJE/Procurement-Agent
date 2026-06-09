---
tags: [tests, phase-1, unit-tests, pytest, bap-monolith, beckn, langgraph]
cssclasses: [procurement-doc, test-doc]
status: "#implemented"
related: ["[[phase1_foundation_protocol_integration]]", "[[beckn_bap_client]]", "[[nl_intent_parser]]", "[[agent_react_framework]]"]
---

# Tests — Phase 1: BAP Monolith (Bap-1)

> [!check] Estado
> **59 tests — todos pasan.** No requieren Docker ni Ollama (el LLM se mockea).
> Ubicación: `Bap-1/tests/`

---

## Correr los tests

```bash
cd Bap-1

# Todos los tests (sin Docker, sin Ollama)
pytest tests/ -v

# Un archivo específico
pytest tests/test_discover.py -v

# Un test específico por nombre
pytest tests/test_discover.py::test_discover_returns_offerings -v

# Solo unit tests del parser (sin Ollama)
pytest tests/test_intent_parser.py -v -k "not integration"

# Tests de integración del parser (requiere Ollama con qwen3:8b)
pytest tests/test_intent_parser.py -v -m integration
```

---

## Cobertura por archivo

### `test_agent.py` — 14 tests · LangGraph ReAct graph

| Test | Qué verifica |
|------|-------------|
| `test_initial_state_all_fields_present` | El estado inicial contiene todos los campos requeridos |
| `test_parse_intent_skipped_when_pre_loaded` | `parse_intent` saltea el NLP si `intent` ya está cargado |
| `test_parse_intent_calls_facade` | `parse_intent` llama a `parse_nl_to_intent()` correctamente |
| `test_discover_returns_3_plus_offerings` | `discover` retorna ≥ 3 offerings del mock ONIX |
| `test_rank_selects_cheapest` | `rank_and_select` elige el offering de menor precio |
| `test_discover_called_with_correct_intent` | El intent correcto se pasa a `discover_async()` |
| `test_transaction_id_propagated` | El `transaction_id` del discover se propaga al estado |
| `test_select_called_with_cheapest_provider` | `/select` se llama con el proveedor más barato |
| `test_select_ack_stored_in_state` | El ACK de `/select` queda en `state["select_ack"]` |
| `test_empty_discover_skips_select` | Sin offerings, el nodo `send_select` se saltea |
| `test_discover_exception_captured` | Excepción en discover queda en `state["error"]` |
| `test_select_exception_captured` | Excepción en select queda en `state["error"]` |
| `test_messages_trace_contains_all_node_tags` | El trace incluye tags de todos los nodos ejecutados |
| `test_messages_are_ordered` | Los mensajes del trace respetan el orden de ejecución |

---

### `test_callbacks.py` — 10 tests · `CallbackCollector`

| Test | Qué verifica |
|------|-------------|
| `test_callback_payload_parses` | `CallbackPayload` se parsea correctamente desde JSON |
| `test_handle_callback_returns_ack` | El handler devuelve `{"message": {"ack": {"status": "ACK"}}}` |
| `test_handle_callback_ignores_unregistered_transaction` | Callbacks sin queue registrada se descartan silenciosamente |
| `test_collect_on_select_response` | `collect()` retorna el payload recibido en la queue |
| `test_collect_returns_empty_for_unregistered` | `collect()` devuelve `[]` si no hay queue para ese `txn_id` |
| `test_collect_timeout_with_no_callback` | `collect()` retorna `[]` tras timeout (sin bloquear indefinidamente) |
| `test_collect_routes_by_action` | Callbacks de `on_discover` no contaminan la queue de `on_select` |
| `test_collect_routes_by_transaction_id` | Callbacks de `txn-A` no contaminan la queue de `txn-B` |
| `test_cleanup_removes_queue` | `cleanup()` elimina la queue del `(txn_id, action)` |
| `test_concurrent_callbacks_all_received` | Múltiples callbacks concurrentes se reciben todos sin pérdida |

---

### `test_discover.py` — 17 tests · `BecknIntent` + `BecknProtocolAdapter` + `BecknClient`

| Test | Qué verifica |
|------|-------------|
| `test_intent_quantity_must_be_positive` | `BecknIntent.quantity` rechaza 0 y negativos |
| `test_intent_negative_quantity_rejected` | `quantity=-1` lanza `ValueError` |
| `test_intent_timeline_must_be_positive` | `delivery_timeline` rechaza valores ≤ 0 |
| `test_intent_timeline_hours_not_iso` | El campo acepta enteros (horas), no strings ISO 8601 |
| `test_intent_budget_range` | `BudgetConstraints` se construye correctamente con `max` y `min` |
| `test_intent_descriptions_atomic_list` | `descriptions` acepta lista de strings atómicos |
| `test_build_discover_request_action` | El payload tiene `action = "discover"` |
| `test_build_discover_request_version` | El payload tiene `version = "2.0.0"` |
| `test_build_discover_request_bap_identity` | El payload lleva el `bap_id` y `bap_uri` correctos |
| `test_build_discover_request_preserves_intent` | El `message` del payload contiene el intent completo |
| `test_discover_url_points_to_onix` | La URL incluye `localhost:8081/bap/caller/discover` |
| `test_discover_url_not_gateway` | La URL nunca apunta directamente a un BPP |
| `test_discover_returns_offerings` | `discover_async()` retorna offerings tras recibir el callback |
| `test_discover_returns_3_plus_sellers` | Se reciben ≥ 3 sellers distintos del mock |
| `test_discover_offerings_have_prices` | Todos los offerings tienen `price_value` numérico |
| `test_discover_with_explicit_transaction_id` | Un `transaction_id` explícito se preserva en el response |
| `test_discover_raises_on_onix_error` | Un HTTP 500 del ONIX lanza excepción en el cliente |

---

### `test_select.py` — 9 tests · `/select` wire format + `BecknClient`

| Test | Qué verifica |
|------|-------------|
| `test_build_select_request_action` | El payload tiene `action = "select"` |
| `test_build_select_request_carries_bpp_context` | El payload lleva `bpp_id` y `bpp_uri` del proveedor elegido |
| `test_build_select_request_preserves_transaction_id` | El `transaction_id` del discover se propaga al select |
| `test_select_url_points_to_onix_adapter` | La URL es `/bap/caller/select` (pasa por ONIX) |
| `test_select_url_not_direct_to_bpp` | La URL nunca contiene la dirección directa del BPP |
| `test_caller_action_url` | `caller_action_url("init")` genera `/bap/caller/init` |
| `test_select_posts_to_onix_adapter` | `client.select()` hace POST al ONIX con el payload correcto |
| `test_select_raises_on_onix_error` | HTTP 500 del ONIX lanza excepción |
| `test_discover_to_select_flow` | Flujo completo mock: discover → obtiene txn_id → select con ese txn_id |

---

### `test_intent_parser.py` — 10 tests · Facade + IntentParser

| Test | Tipo | Qué verifica |
|------|------|-------------|
| `test_bridge_returns_none_for_non_procurement` | Unit | Queries no-procurement retornan `None` |
| `test_bridge_converts_to_bap_beckn_intent` | Unit | El resultado es una instancia de `BecknIntent` de `shared/models` |
| `test_bridge_preserves_delivery_timeline_in_hours` | Unit | "3 days" → `72` (horas), no ISO 8601 |
| `test_bridge_preserves_budget_constraints` | Unit | Presupuesto se mapea a `BudgetConstraints {max, min}` |
| `test_bridge_preserves_location_coordinates` | Unit | "Bangalore" → `"12.9716,77.5946"` |
| `test_bridge_preserves_descriptions_list` | Unit | Specs técnicas se mapean a `descriptions: list[str]` |
| `test_bridge_result_accepted_by_adapter` | Unit | El `BecknIntent` resultante es aceptado por `BecknProtocolAdapter` |
| `test_integration_parse_nl_to_intent[query0]` | Integration | "500 reams A4 paper…" → intent válido con Ollama real |
| `test_integration_parse_nl_to_intent[query1]` | Integration | "100 ethernet cables…" → intent válido con Ollama real |
| `test_integration_parse_nl_to_intent[query2]` | Integration | "request quote for 200 chairs…" → intent válido con Ollama real |

> Los tests de integración (`-m integration`) requieren Ollama corriendo con `qwen3:8b`.

---

## Smoke test manual — flujo completo (Bap-1)

### Prerequisitos

```bash
# 1. Docker stack (onix-bap, onix-bpp, sandbox-bpp, redis)
cd starter-kit/generic-devkit/install
docker compose -f docker-compose-my-bap.yml up -d

# 2. Ollama (solo para modo NL query)
ollama run qwen3:1.7b
```

### Opción A — CLI

```bash
cd Bap-1

# Con NL query (usa Ollama)
python run.py "500 reams A4 paper 80gsm Bangalore 3 days max 200 INR"

# Con intent hardcodeado (sin Ollama)
python run.py
```

**Output esperado:**
```
============================================================
  Procurement ReAct Agent — Beckn Protocol v2
============================================================
  BAP ID   : procurement-bap
  ONIX URL : http://localhost:8081
  Mode     : NL query

  Running agent...

    [parse_intent]    item='A4 paper 80gsm' qty=500 loc=12.9716,77.5946 timeline=72h budget_max=200.0
    [discover]        txn=abc-123 found 3 offering(s): OfficeWorld@₹195, PaperDirect@₹189, StationeryHub@₹201
    [rank_and_select] selected 'PaperDirect' ₹189 (cheapest of 3)
    [send_select]     ACK=ACK bpp=seller-2 provider=PaperDirect
    [present_results] Order initiated — PaperDirect | A4 Paper Ream × 500 | ₹189 INR | txn=abc-123

  Done. Next: /init -> /confirm -> /status
============================================================
```

### Opción B — Con frontend

```bash
# Terminal 1
cd Bap-1 && python -m src.server

# Terminal 2
cd frontend && npm install && npm run dev
```

Abrir `http://localhost:3000` — login con `priya@example.com` / `password123`.
