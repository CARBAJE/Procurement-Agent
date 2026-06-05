---
tags: [tests, phase-2, data-normalizer, persistence, postgres, audit, pytest, asyncpg]
cssclasses: [procurement-doc, test-doc]
status: "#implemented"
related: ["[[phase2_microservices]]", "[[data_normalizer]]", "[[microservices_architecture]]"]
---

# Tests — Data Normalizer (Phase 2)

> [!architecture] Contexto
> Antes de esta iteración el servicio `data-normalizer` **no tenía un solo test**. La pipeline de persistencia (`request → intent → discovery → scoring → order` + status) se validaba a mano contra una BD real.
> Esta suite añade **59 tests** (35 unit + 24 integración) y además cierra tres huecos de auditoría que la exploración detectó:
> - **`audit_trail_events`** nunca se escribía → se añadió `POST /normalize/audit` + `_persist_audit` en cada hito del orchestrator.
> - **`/status`** no persistía transiciones del pedido → se añadió `PATCH /normalize/po_status` y se cableó en `order_status`.
> - **Errores de BD** caían como 500 genérico → middleware de `asyncpg` mapea a 409/422/500 estructurados.

---

## 0 — Estructura de la suite

| Capa | Ubicación | Backend | Tests |
|------|-----------|---------|-------|
| Unit | `DataNormalizer/tests/` | `asyncpg` mockeado (`AsyncMock`) | 35 |
| Integración | `services/data-normalizer/tests/` | Postgres real (auto-creada `procurement_agent_test`) | 24 |
| **Total** | | | **59** |

> [!info] Aislamiento entre suites
> El conftest unit (`DataNormalizer/tests/conftest.py`) escope su `patch_db_pool` autouse a su propio directorio. Cuando ambas suites se invocan en el mismo `pytest`, los tests de integración no se ven afectados por los mocks de la suite unit.

---

## 1 — Tests Unit (`DataNormalizer/tests/`)

Mockean `db.get_pool()` y la `Connection` adquirida con `AsyncMock`. No tocan Postgres en absoluto. Verifican lógica de repos (defaults, clampeos, validaciones de enums) y el facade.

### 1.1 `test_request_repo.py` (4 tests)

| Test | Verifica |
|------|----------|
| `test_create_request_happy_path` | INSERT en `procurement_requests` con los args correctos, status='draft' por defecto. |
| `test_create_request_invalid_channel_defaults_to_web` | `channel='carrier-pigeon'` se coerce a `'web'` y emite WARNING. |
| `test_create_request_uses_system_user_when_no_requester` | Sin `requester_id` usa `SYSTEM_USER_ID` del env. |
| `test_update_status_executes_update` | `update_status` genera el UPDATE correcto. |

### 1.2 `test_intent_repo.py` (6 tests)

| Test | Verifica |
|------|----------|
| `test_create_parsed_intent_happy_path` | INSERT con args correctos. |
| `test_create_parsed_intent_clamps_confidence_above_one` | `confidence=1.5` → `1.0` + WARNING. |
| `test_create_parsed_intent_clamps_confidence_below_zero` | `confidence=-0.3` → `0.0`. |
| `test_create_parsed_intent_invalid_class_defaults` | `intent_class='garbage'` → `'out_of_scope'` + WARNING. |
| `test_create_beckn_intent_applies_all_defaults` | Payload vacío → `item='unknown'`, `unit='units'`, coords `'0.0,0.0'`, timeline `72`, currency `'INR'`. Emite 4 WARNINGs. |
| `test_create_beckn_intent_passes_through_provided_values` | Cuando el payload es completo, nada se coerce. |

### 1.3 `test_discovery_repo.py` (5 tests)

| Test | Verifica |
|------|----------|
| `test_upsert_bpp_returns_existing` | SELECT → encuentra → UPDATE `last_seen_at`, devuelve UUID existente. |
| `test_upsert_bpp_creates_new_when_missing` | SELECT → None → INSERT, devuelve nuevo UUID. |
| `test_create_discovery_inserts_query_and_offerings` | Crea `discovery_queries` + `seller_offerings` + upsert de `bpp` en una sola transacción. |
| `test_create_discovery_clamps_negative_delivery_eta` | `fulfillment_hours=-5` → `1` (respeta CHECK > 0) + WARNING. |
| `test_create_discovery_non_numeric_price_defaults_to_zero` | `price_value='not-a-number'` → `0.0` + WARNING. |

### 1.4 `test_scoring_repo.py` (4 tests)

| Test | Verifica |
|------|----------|
| `test_create_scores_happy_path_scales_score_x100` | `composite_score=0.85` → `total_score=85.0`. |
| `test_create_scores_clamps_above_one_to_100` | `composite_score=1.5` → `100.0` + WARNING. |
| `test_create_scores_skips_entries_without_offering_id` | Entradas sin `offering_id` se ignoran silenciosamente (no rompen). |
| `test_create_scores_non_numeric_tco_defaults_to_zero` | `price_value='not-a-number'` → tco `0.0` + WARNING. |

### 1.5 `test_order_repo.py` (6 tests)

| Test | Verifica |
|------|----------|
| `test_create_order_full_fk_chain` | Una sola transacción crea `negotiation_outcomes → approval_decisions → purchase_orders`. `amount_total = price × quantity`. |
| `test_create_order_amount_total_clamps_quantity_to_one` | `quantity=0` → `max(1, 0) = 1` para el cálculo de `amount_total`. |
| `test_create_order_defaults_to_system_user` | `requester_id=None` → `SYSTEM_USER_ID`. |
| `test_update_po_status_returns_po_id_when_matched` | UPDATE encuentra → devuelve `po_id`. |
| `test_update_po_status_returns_none_when_no_match` | `beckn_confirm_ref` desconocido → `None` (no falla). |
| `test_update_po_status_rejects_invalid_state` | `state='invented'` → `ValueError` antes de tocar la BD. |

### 1.6 `test_audit_repo.py` (5 tests)

| Test | Verifica |
|------|----------|
| `test_create_audit_event_happy_path` | INSERT con `reasoning_payload` JSON serializado correctamente. |
| `test_create_audit_event_rejects_invalid_event_type` | `event_type='not_an_event'` → `ValueError` antes de tocar la BD. |
| `test_create_audit_event_requires_action` | `agent_action=''` → `ValueError`. |
| `test_create_audit_event_handles_optional_uuids` | Sin `request_id` / `po_id` / `actor_id` → pasa `None` a la BD (FK nullables). |
| `test_create_audit_event_accepts_empty_payload` | `reasoning_payload=None` → `'{}'` en JSON. |

### 1.7 `test_normalizer_facade.py` (5 tests)

Verifican que el facade `DataNormalizer` delega correctamente a los repos con los args correctos. Cada método (`normalize_request`, `normalize_intent`, `normalize_audit`, `normalize_po_status`, `update_status`) tiene su test de delegación.

---

## 2 — Tests de Integración (`services/data-normalizer/tests/`)

Levantan un Postgres real, aplican el schema completo de `database/sql/*.sql`, y ejercen los endpoints HTTP con `aiohttp.TestClient`. Cada test arranca con la BD limpia (TRUNCATE respetando FKs).

### 2.1 Fixtures clave (`conftest.py`)

| Fixture | Rol |
|---------|-----|
| `_ensure_database_exists` | Crea `procurement_agent_test` si no existe (conecta a `postgres` como admin). |
| `_apply_schema` | Aplica los 18 archivos `database/sql/*.sql` en orden lexicográfico. Idempotente. |
| `schema_applied` | Session-scoped — corre el bootstrap una vez. |
| `db_pool` | Function-scoped — pool fresco por test; resetea `DataNormalizer.db._pool` para evitar pools atados a loops cerrados. |
| `clean_db` | TRUNCATE de las 11 tablas auditables en orden FK-safe. |
| `client` | `aiohttp.TestClient` con `create_app()` (incluye `db_error_middleware`). |

> [!tip] Auto-detección del backend
> El conftest intenta primero `testcontainers.postgres.PostgresContainer` (requiere Docker). Si no está disponible, cae al Postgres local con DSN derivado de `TEST_DB_HOST / TEST_DB_PORT / TEST_DB_USER`. Forzar el path local con `USE_LOCAL_PG=1`.

### 2.2 `test_endpoints.py` — 23 tests

#### Happy path por endpoint (8)

| Test | Endpoint | Lo que valida en BD |
|------|----------|---------------------|
| `test_normalize_request_creates_row` | `POST /normalize/request` | Fila en `procurement_requests` con `status='draft'` y `channel='web'`. |
| `test_normalize_intent_creates_both_rows` | `POST /normalize/intent` | Fila en `parsed_intents` + `beckn_intents` con FK al request. |
| `test_normalize_discovery_creates_query_and_offerings` | `POST /normalize/discovery` | `discovery_queries` + 2 `seller_offerings` + 2 `bpp` (uno por uri única). |
| `test_normalize_scoring_creates_scored_offers` | `POST /normalize/scoring` | 2 `scored_offers` con `total_score` correctamente escalado (×100). |
| `test_normalize_order_creates_full_fk_chain` | `POST /normalize/order` | Cadena `negotiation_outcomes → approval_decisions → purchase_orders` con `acceptance_status='skipped'` y `status='auto_approved'`. |
| `test_patch_status_updates_request` | `PATCH /normalize/status` | `procurement_requests.status='cancelled'`. |
| `test_patch_po_status_updates_by_confirm_ref` | `PATCH /normalize/po_status` | `purchase_orders.status='shipped'` localizado vía `beckn_confirm_ref`. |
| `test_post_audit_appends_event` | `POST /normalize/audit` | `audit_trail_events` con `event_type='normalize'` y FK al `request_id`. |

#### Validación 400 (parametrizado — 9 casos)

`test_validation_errors_return_400` cubre, para cada endpoint, el caso de campos requeridos faltantes:

- `/normalize/request` sin `raw_input_text` (y con blanco después de trim).
- `/normalize/intent` sin `request_id` o sin `beckn_intent`.
- `/normalize/discovery` sin `beckn_intent_id`.
- `/normalize/scoring` sin `query_id`.
- `/normalize/order` sin alguno de los 5 requeridos.
- `/normalize/audit` sin `event_type` o con valor fuera del enum.

Más:
- `test_patch_status_missing_fields_returns_400`
- `test_patch_po_status_invalid_state_returns_400` (`state='invented'`).

#### Errores estructurados de BD (2)

| Test | Verifica |
|------|----------|
| `test_fk_violation_on_intent_returns_409` | `request_id` inexistente → 409 con `{"error": "fk_violation"}` (antes del middleware era 500 opaco). |
| `test_unique_violation_on_duplicate_intent_returns_409` | Doble `POST /normalize/intent` con mismo `request_id` → 409 con `{"error": "duplicate"}`. |

#### Defaults silenciosos verificados en BD (2)

| Test | Verifica |
|------|----------|
| `test_invalid_channel_silently_defaulted_to_web` | `channel='carrier-pigeon'` → 201 y la fila guarda `'web'`. |
| `test_confidence_above_one_gets_clamped` | `confidence=1.7` → 201 y `parsed_intents.confidence_score=1.0`. |

### 2.3 `test_full_pipeline.py` — 1 test E2E

`test_full_pipeline_request_to_confirmed_order` recorre la pipeline completa mediante HTTP:

1. `POST /normalize/request` con `raw_input_text` real.
2. `POST /normalize/intent` con `BecknIntent` realista (item, qty, coords, budget).
3. `POST /normalize/discovery` con 3 ofertas.
4. `POST /normalize/scoring` con 3 ranks.
5. `PATCH /normalize/status` → `negotiating`.
6. `POST /normalize/order` sobre la ganadora.
7. `PATCH /normalize/status` → `confirmed`.
8. `POST /normalize/audit` × 3 (normalize, score, confirm).
9. `PATCH /normalize/po_status` × 2 (shipped → delivered).

Y luego valida la BD con un único SELECT que recorre toda la cadena FK:
- `procurement_requests.status='confirmed'`.
- 3 `seller_offerings` para esa `query_id`.
- 3 `scored_offers` enlazados.
- `purchase_orders.status='delivered'` con el `beckn_confirm_ref` correcto.
- 3 filas en `audit_trail_events` con el `request_id`.

---

## 3 — Cómo correr la suite

### Pre-requisitos

```bash
# Para la suite unit — solo Python:
pip install pytest pytest-asyncio asyncpg aiohttp

# Para la suite de integración — además de lo anterior:
# (a) Postgres local accesible — la suite crea `procurement_agent_test` por sí misma.
# (b) O bien Docker:
pip install testcontainers
```

### Comandos

```bash
# Desde la raíz del repositorio:

# Solo unit (rápido, no necesita BD):
python -m pytest DataNormalizer/tests/ -v

# Solo integración (~1.5 s con Postgres local):
python -m pytest services/data-normalizer/tests/ -v

# Ambas:
python -m pytest DataNormalizer/tests/ services/data-normalizer/tests/ -v
```

### Salida esperada

```
DataNormalizer/tests/                          35 passed
services/data-normalizer/tests/                24 passed
─────────────────────────────────────────────────────────
                                              59 passed
```

---

## 4 — Trazabilidad con los huecos cerrados

| Hueco identificado en la exploración | Test que lo verifica |
|---|---|
| `audit_trail_events` sin escrituras | `test_audit_repo.py` (5) + `test_post_audit_appends_event` + asserción de `audit_count == 3` en `test_full_pipeline` |
| `purchase_orders.status` siempre `pending` | `test_update_po_status_*` (3) + `test_patch_po_status_updates_by_confirm_ref` + asserción `po_status='delivered'` en `test_full_pipeline` |
| `FK violations` caían como 500 | `test_fk_violation_on_intent_returns_409` |
| `UNIQUE violations` caían como 500 | `test_unique_violation_on_duplicate_intent_returns_409` |
| Defaults silenciosos sin logs | Todos los tests `*_clamps_*`, `*_defaults_*`, `*_non_numeric_*` (8 unit) capturan el WARNING con `caplog` |
| Cadena FK completa sin verificar | `test_normalize_order_creates_full_fk_chain` (unit) + `test_full_pipeline_request_to_confirmed_order` (integración) |

---

## 5 — Mantenimiento

> [!warning] Cuando añadas un nuevo endpoint al data-normalizer
> 1. Añade el test unit del repo en `DataNormalizer/tests/test_<nombre>_repo.py`.
> 2. Añade el test del facade en `test_normalizer_facade.py`.
> 3. Añade el happy path en `services/data-normalizer/tests/test_endpoints.py`.
> 4. Si el endpoint puede fallar por validación o constraints, añade el caso al `pytest.mark.parametrize` de `test_validation_errors_return_400` o un test específico de 409/422.
> 5. Si el endpoint participa en el ciclo de vida de una request, añade el paso a `test_full_pipeline.py`.

> [!info] Si cambias el schema (`database/sql/*.sql`)
> No hace falta tocar los tests de integración. El conftest aplica los archivos en orden lexicográfico — solo asegúrate de que el orden de los `NN_*.sql` siga reflejando dependencias de FK.
