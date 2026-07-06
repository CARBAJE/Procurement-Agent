# Phase 3 — Audit Trail System: Tests y Guía de Verificación

> Componente: [[audit_trail_system]]
> Rama: `feature/agent-memory-learning`
> Spec: `components/audit_trail_system.md`

---

## Qué está implementado

### Arquitectura desplegada

```
Acción del agente (cualquier paso del pipeline)
        ↓
orchestrator: await _persist_audit(session, event_type, agent_action,
                                   reasoning_payload, request_id, po_id)
  └─ fire-and-forget — nunca interrumpe el flujo principal
        ↓
POST /normalize/audit   (data-normalizer :8006)
        ↓
INSERT INTO audit_trail_events (PostgreSQL 16)
  - event_type:        audit_event_type ENUM (9 valores)
  - agent_action:      TEXT (descripción de la acción)
  - reasoning_payload: JSONB (inputs, outputs, scores, trazas LLM)
  - kafka_offset:      BIGINT (placeholder para integración futura)
  - retention_until:   NOW() + 7 años (SOX 404 / GDPR / IT Act 2000)

─────────────────────────────────────────────────────────────────────

Consulta de auditoría (compliance officer / frontend)
        ↓
GET /normalize/audit?request_id=X         ← cadena completa de un pedido
GET /normalize/audit?po_id=X              ← eventos de una PO confirmada
GET /normalize/audit/{event_id}           ← evento individual con payload
        ↓
Frontend: /request/{id}/audit
  └─ AuditTrailPanel (timeline vertical, payload colapsable)
```

### Puntos de escritura en el pipeline (20+ eventos)

| Etapa | event_type | agent_action |
|---|---|---|
| Creación de solicitud | `normalize` | `request_created` |
| Persistencia de intent | `normalize` | `intent_persisted` |
| Ejecución de discovery | `discover` | `discovery_executed` |
| Scoring de ofertas | `score` | `offerings_scored` |
| Negociación | `negotiate` | `negotiation_step` / `counter_sent` |
| Confirmación de pedido | `confirm` | `order_confirmed` |
| Cambio de estado PO | `normalize` | `po_status_updated` |
| Override del usuario | `override` | `user_overrode_recommendation` |
| Notificación | `notification` | `notification_sent` |
| Sync ERP | `erp_sync` | `erp_budget_checked` / `erp_po_created` |

### Archivos clave

| Archivo | Rol |
|---|---|
| `database/sql/14_audit_trail_events.sql` | Schema: tabla + enum `audit_event_type` |
| `database/sql/17_indexes.sql` | 4 índices optimizados (request, type, po, splunk_pending) |
| `DataNormalizer/repositories/audit_repo.py` | Write: `create_audit_event()` · Read: `get_events_by_request()`, `get_events_by_po()`, `get_event_by_id()` |
| `DataNormalizer/normalizer.py` | Facade con métodos `normalize_audit()` y los 3 getters |
| `services/data-normalizer/src/handler.py` | POST + GET `/normalize/audit` + GET `/normalize/audit/{event_id}` |
| `services/orchestrator/src/workflow.py` | `_persist_audit()` + 20+ puntos de llamada |
| `frontend/src/app/api/audit/route.ts` | Proxy Next.js → data-normalizer |
| `frontend/src/components/procurement/AuditTrailPanel.tsx` | Timeline con iconos por tipo y payload colapsable |
| `frontend/src/components/procurement/AuditTrailView.tsx` | Componente cliente con carga async + error state |
| `frontend/src/app/request/[id]/audit/page.tsx` | Página SSR autenticada |

### Limitaciones actuales vs. spec

| Aspecto | Spec | Implementado |
|---|---|---|
| Event bus | Kafka (7 años, replication ≥ 3) | `kafka_offset` columna existe como placeholder; envío real diferido a Phase 4 |
| SIEM sink | Splunk + ServiceNow batch consumer | `splunk_indexed` columna existe; exportador diferido a Phase 4 |
| LLM traces | LangSmith integration | `reasoning_payload` captura los datos; integración LangSmith pendiente |
| Retention enforcement | Nightly DELETE/archival job | `retention_until` columna existe; job de limpieza diferido a Phase 4 |

---

## Prerrequisitos para testear

```bash
# 1. Stack completo corriendo
docker compose up -d
docker compose ps   # data-normalizer y orchestrator deben estar Up

# 2. Verifica que la tabla existe con las columnas correctas
psql -U postgres -d procurement_agent -c "\d audit_trail_events"
# Debe mostrar: event_id, request_id, po_id, actor_id, event_type,
#               agent_action, reasoning_payload, kafka_offset,
#               splunk_indexed, event_timestamp, retention_until

# 3. Verifica que el endpoint de escritura responde
curl -s http://localhost:8006/health
# → {"status": "ok", "service": "data-normalizer"}
```

---

## Test 1 — Write path: verificar que los eventos se escriben durante el flujo

### Paso 1 — Observa el conteo inicial

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT COUNT(*) FROM audit_trail_events;"
```

### Paso 2 — Realiza un pedido completo en el frontend

1. Abre `http://localhost:3000` y haz login
2. Escribe: **"200 resmas papel A4 Chennai 2 días"**
3. Espera que aparezcan los proveedores y el scoring
4. Selecciona un proveedor → haz clic en **Commit / Confirm Order**
5. Espera a que el estado avance a `confirmed`

### Paso 3 — Verifica los eventos en la BD

```bash
psql -U postgres -d procurement_agent -c "
SELECT event_type, agent_action, event_timestamp
FROM audit_trail_events
ORDER BY event_timestamp DESC
LIMIT 10;"
```

**Resultado esperado** — al menos estos 3 eventos en orden cronológico:

| event_type | agent_action |
|---|---|
| `normalize` | `request_created` |
| `normalize` | `intent_persisted` |
| `discover` | `discovery_executed` |
| `score` | `offerings_scored` |
| `confirm` | `order_confirmed` |

También en los logs:

```bash
docker compose logs orchestrator | grep "audit"
# → INFO:__main__:[audit] normalize (request_created) → <event_id>
# → INFO:__main__:[audit] confirm (order_confirmed) → <event_id>
```

### Paso 4 — Escribe un evento manualmente vía API

```bash
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{
    "event_type":        "score",
    "agent_action":      "manual test event",
    "reasoning_payload": {"items": 3, "top_score": 0.92}
  }' | python3 -m json.tool
# → {"event_id": "<uuid>"}
```

---

## Test 2 — Read path: consultar la cadena de decisiones de un request

> Requiere haber completado Test 1 (al menos 1 pedido con `request_id`).

### Paso 1 — Obtén el request_id del pedido

```bash
psql -U postgres -d procurement_agent -c "
SELECT request_id, raw_input_text, created_at
FROM procurement_requests
ORDER BY created_at DESC LIMIT 3;"
```

### Paso 2 — Consulta todos los eventos del request via API

```bash
export REQUEST_ID="<uuid-del-paso-1>"

curl -s "http://localhost:8006/normalize/audit?request_id=$REQUEST_ID" \
  | python3 -m json.tool
```

**Resultado esperado:**

```json
{
  "count": 5,
  "events": [
    {
      "event_id": "...",
      "event_type": "normalize",
      "agent_action": "request_created",
      "reasoning_payload": {"raw_query": "200 resmas papel A4..."},
      "event_timestamp": "2026-07-06T10:23:01.123456",
      "retention_until": "2033-07-06T10:23:01.123456",
      "splunk_indexed": false
    },
    ...
  ]
}
```

La cadena completa de decisiones debe ser **reconstruíble únicamente desde estos eventos** — sin estado de la aplicación.

### Paso 3 — Consulta un evento individual

```bash
export EVENT_ID=$(curl -s "http://localhost:8006/normalize/audit?request_id=$REQUEST_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['events'][0]['event_id'])")

curl -s "http://localhost:8006/normalize/audit/$EVENT_ID" | python3 -m json.tool
# → evento completo con reasoning_payload expandido
```

### Paso 4 — Consulta por PO (post-confirmación)

```bash
export PO_ID=$(psql -U postgres -d procurement_agent -At -c \
  "SELECT po_id FROM purchase_orders ORDER BY created_at DESC LIMIT 1;")

curl -s "http://localhost:8006/normalize/audit?po_id=$PO_ID" \
  | python3 -m json.tool
# → eventos confirm, erp_sync, notification relacionados con la PO
```

---

## Test 3 — Frontend: visualización del Audit Trail en el browser

> Requiere un pedido confirmado con `request_id` conocido.

### Paso 1 — Navega a la página de audit trail

```
http://localhost:3000/request/<request_id>/audit
```

### Paso 2 — Verifica el timeline

La página debe mostrar el componente **AuditTrailPanel** con:
- Un nodo por cada evento, ordenados cronológicamente (ASC)
- Ícono y color diferente por tipo (`normalize`=gris, `score`=purple, `confirm`=verde, `override`=naranja...)
- Badge con el tipo de evento
- Timestamp formateado (`Jul 6, 2026, 10:23 AM`)
- Botón **"Show reasoning payload"** que expande el JSON completo

### Paso 3 — Verifica el empty state

Navega con un `request_id` sin eventos:

```
http://localhost:3000/request/00000000-0000-0000-0000-000000000000/audit
```

Debe mostrar el empty state con ícono y mensaje "No audit events recorded yet."

---

## Test 4 — Validaciones del endpoint

```bash
# event_type inválido → 400
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{"event_type": "invalid_type", "agent_action": "test"}' -w "\n%{http_code}"
# → 400

# Sin agent_action → 400
curl -s -X POST http://localhost:8006/normalize/audit \
  -H "Content-Type: application/json" \
  -d '{"event_type": "score"}' -w "\n%{http_code}"
# → 400

# GET sin parámetros → 400
curl -s "http://localhost:8006/normalize/audit" -w "\n%{http_code}"
# → 400  (request_id or po_id query parameter is required)

# GET event_id inexistente → 404
curl -s "http://localhost:8006/normalize/audit/00000000-0000-0000-0000-000000000000" \
  -w "\n%{http_code}"
# → 404
```

---

## Tests automatizados

```bash
# Desde services/data-normalizer/
cd services/data-normalizer
PYTHONPATH=<repo_root> .venv-test/bin/python -m pytest tests/test_endpoints.py -k "audit" -v

# Resultado esperado (10 tests):
# PASSED test_post_audit_appends_event
# PASSED test_validation_errors_return_400[/normalize/audit-body7]
# PASSED test_validation_errors_return_400[/normalize/audit-body8]
# PASSED test_audit_get_by_request_id_returns_events
# PASSED test_audit_get_by_request_id_empty_when_no_events
# PASSED test_audit_get_by_po_id_returns_events
# PASSED test_audit_get_missing_param_returns_400
# PASSED test_audit_get_event_by_id
# PASSED test_audit_get_event_by_id_not_found_404
# PASSED test_audit_get_limit_respected
```

---

## Solución de problemas

### Los eventos no aparecen en la BD tras un pedido

```bash
docker compose logs orchestrator | grep -E "audit|persist"
# Si no hay líneas: _persist_audit() no se está llamando
# Si hay "WARNING [persist_audit] failed": el data-normalizer no está disponible
```

Verifica que `DATA_NORMALIZER_URL` está configurado en el orchestrator:

```bash
docker compose exec orchestrator env | grep DATA_NORMALIZER
# → DATA_NORMALIZER_URL=http://data-normalizer:8006
```

### `GET /normalize/audit` devuelve 500

Verifica que la tabla `audit_trail_events` tiene todas las columnas esperadas:

```bash
psql -U postgres -d procurement_agent -c "\d audit_trail_events"
```

Si falta `retention_until`, la migración `14_audit_trail_events.sql` no se aplicó correctamente. Vuelve a ejecutar:

```bash
python database/setup_database.py
```

### El frontend muestra "data-normalizer unavailable" (502)

El proxy Next.js en `/api/audit/route.ts` usa `DATA_NORMALIZER_URL` del entorno del servidor Next.js (no del contenedor). En desarrollo local:

```bash
# .env.local del frontend
DATA_NORMALIZER_URL=http://localhost:8006
```

### Los eventos tienen `reasoning_payload: {}` vacío

Esto es válido — el orchestrator omite el payload en eventos de bajo nivel. Para los eventos de scoring y confirm, el payload debe tener contenido:

```bash
psql -U postgres -d procurement_agent -c "
SELECT agent_action, jsonb_pretty(reasoning_payload)
FROM audit_trail_events
WHERE event_type = 'score'
ORDER BY event_timestamp DESC LIMIT 1;"
```

---

## Checklist de aceptación (Phase 3)

- [ ] `audit_trail_events` existe con enum `audit_event_type` y 9 valores válidos
- [ ] `POST /normalize/audit` devuelve `{"event_id": "<uuid>"}` con status 201
- [ ] `GET /normalize/audit?request_id=X` devuelve la cadena completa de eventos en orden cronológico
- [ ] `GET /normalize/audit/{event_id}` devuelve el evento individual con `reasoning_payload`
- [ ] Al confirmar un pedido en el frontend, al menos 4 eventos se persisten automáticamente
- [ ] `retention_until` es `event_timestamp + 7 años` en todos los eventos
- [ ] El frontend `/request/{id}/audit` muestra el timeline con iconos y payloads colapsables
- [ ] Validaciones retornan 400 para `event_type` inválido y `agent_action` vacío
- [ ] Un event_id inexistente retorna 404
- [ ] La cadena de decisiones es **reconstruíble exclusivamente desde los eventos** — sin estado de la aplicación (cumple SOX 404)
