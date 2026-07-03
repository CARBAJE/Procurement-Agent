# Phase 3 — Agent Memory & Learning: Tests y Guía de Verificación

> Componente: [[agent_memory_learning]]
> Rama: `feature/agent-memory-learning`
> Spec: `components/agent_memory_learning.md`

---

## Qué está implementado

### Arquitectura desplegada

```
Pedido confirmado (commit)
        ↓
orchestrator: asyncio.create_task(_persist_memory(...))   ← fire-and-forget
        ↓
POST /normalize/memory/write   (data-normalizer :8006)
        ↓
fastembed BAAI/bge-small-en-v1.5 → vector(384) ONNX, sin PyTorch
        ↓
INSERT INTO agent_memory_vectors (pgvector HNSW cosine)

─────────────────────────────────────────────────────────

Nueva solicitud (compare)
        ↓
orchestrator: _fetch_memory_context(item_text, limit=3)   ← timeout 5s
        ↓
POST /normalize/memory/search   (data-normalizer :8006)
        ↓
ANN cosine search (HNSW, sim ≥ 0.75) → top-3 transacciones similares
        ↓
reasoning_steps += { node: "memory_context", role: "observe", ... }
        ↓
Frontend: nodo visible en el panel de razonamiento del agente
```

### Archivos clave

| Archivo | Rol |
|---|---|
| `database/sql/22_agent_memory_vector_dim.sql` | Migración: `vector(384)` + índice HNSW cosine |
| `DataNormalizer/repositories/memory_repo.py` | Embedding con fastembed + write/search en pgvector |
| `DataNormalizer/normalizer.py` | Métodos `write_memory()` y `search_memory()` |
| `services/data-normalizer/src/handler.py` | Endpoints `POST /normalize/memory/write` y `POST /normalize/memory/search` |
| `services/orchestrator/src/workflow.py` | `_persist_memory()` (write) + `_fetch_memory_context()` (read) |

### Limitaciones actuales vs. spec

| Aspecto | Spec | Implementado |
|---|---|---|
| Vector store | Qdrant (HNSW) + pgvector mirror | Solo pgvector (suficiente para < 100K registros) |
| Modelo de embedding | text-embedding-3-large (3072 dims) | BAAI/bge-small-en-v1.5 (384 dims, ONNX, local) |
| ETL nightly | PostgreSQL → Qdrant batch sync | No aplica (pgvector es el store único) |
| Model governance | Pipeline semanal con LangSmith | Schema creado, pipeline pendiente |
| Datos de entrenamiento | ERP exports, user logs, supplier data | Solo transacciones confirmadas en el flujo Beckn |

---

## Prerrequisitos para testear

```bash
# 1. Asegúrate de que todos los servicios corren
docker compose up -d
docker compose ps   # data-normalizer y orchestrator deben estar Up

# 2. Verifica que la migración 22 está aplicada
psql -U postgres -d procurement_agent -c "\d agent_memory_vectors"
# Debes ver: embedding_vector | vector(384)
# e índice: idx_agent_memory_hnsw | hnsw (embedding_vector vector_cosine_ops)

# 3. Verifica que los endpoints existen
curl -s http://localhost:8006/health
# → {"status": "ok", "service": "data-normalizer"}
```

---

## Test 1 — Write Path: confirmar que la memoria se escribe tras un pedido

### Paso 1 — Verifica el conteo inicial

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT COUNT(*) FROM agent_memory_vectors;"
# → 0  (o el número de pedidos previos confirmados)
```

### Paso 2 — Realiza un pedido completo en el frontend

1. Abre el frontend: `http://localhost:3000`
2. Login con tus credenciales Keycloak
3. Escribe una solicitud en el chat, por ejemplo: **"500 resmas papel A4 Bangalore 3 días"**
4. Espera a que aparezcan los proveedores en el panel de comparación
5. Selecciona un proveedor y haz clic en **Commit / Confirm Order**
6. Espera a que el estado avance a `confirmed`

### Paso 3 — Verifica que la memoria se escribió

```bash
psql -U postgres -d procurement_agent -c \
  "SELECT metadata->>'text_summary', metadata->>'provider_name', indexed_at
   FROM agent_memory_vectors
   ORDER BY indexed_at DESC LIMIT 5;"
```

**Resultado esperado:**

| text_summary | provider_name | indexed_at |
|---|---|---|
| `papel A4 ordered from OfficeZone India at 480.00 INR delivery in 72h` | `OfficeZone India` | `2026-07-03 ...` |

También en los logs del orchestrator:

```bash
docker compose logs orchestrator | grep memory
# → INFO:__main__:[memory] stored transaction for papel A4
```

---

## Test 2 — Read Path: verificar el nodo `memory_context` en el frontend

> Requiere haber completado Test 1 primero (al menos 1 pedido en memoria).

### Paso 1 — Realiza una segunda solicitud del mismo tipo de ítem

1. En el frontend, inicia una **nueva solicitud** con un ítem similar al del pedido anterior: **"300 resmas papel A4 Mumbai"**
2. Espera a que el agente procese y aparezcan los proveedores

### Paso 2 — Busca el nodo `memory_context` en el panel de razonamiento

En la interfaz, el panel de **Agent Reasoning** debe mostrar un nuevo nodo:

```
📋 memory_context  [observe]
Found 1 similar past order(s):
  OfficeZone India ₹480.0 INR (72h)
```

### Paso 3 — Verifica también via API directa

```bash
# Busca manualmente con el texto del ítem:
curl -s -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "papel A4 resmas", "limit": 3}' | python3 -m json.tool
```

**Resultado esperado:**

```json
{
  "results": [
    {
      "item_text": "papel A4",
      "provider_name": "OfficeZone India",
      "price": 480.0,
      "currency": "INR",
      "delivery_hours": 72,
      "text_summary": "papel A4 ordered from OfficeZone India at 480.00 INR delivery in 72h",
      "similarity": 0.87
    }
  ],
  "count": 1
}
```

Si `similarity < 0.75`, el resultado es filtrado y no aparece en el panel — esto es correcto.

---

## Test 3 — Aislamiento y umbral de similitud

Verifica que la memoria **no** contamina solicitudes de ítems completamente distintos.

```bash
# Solicitar algo sin relación al papel:
curl -s -X POST http://localhost:8006/normalize/memory/search \
  -H "Content-Type: application/json" \
  -d '{"item_text": "laptops Dell 16GB RAM", "limit": 3}'
# → {"results": [], "count": 0}
```

---

## Test 4 — Verificación de la BD post múltiples pedidos

Después de 3+ pedidos de distintos ítems:

```bash
psql -U postgres -d procurement_agent -c "
SELECT
  entity_type,
  metadata->>'item_text'     AS item,
  metadata->>'provider_name' AS provider,
  (metadata->>'price')::numeric AS price,
  indexed_at::date            AS fecha
FROM agent_memory_vectors
ORDER BY indexed_at DESC;"
```

Todos deben ser `entity_type = 'transaction'`.

---

## Solución de problemas

### El nodo `memory_context` no aparece en el frontend

1. Revisa logs del orchestrator:
   ```bash
   docker compose logs orchestrator | grep -E "memory|fetch"
   ```
2. Verifica que `agent_memory_vectors` tiene filas:
   ```bash
   psql -U postgres -d procurement_agent -c "SELECT COUNT(*) FROM agent_memory_vectors;"
   ```
3. Prueba la búsqueda directa con el endpoint para ver el score real.
4. El umbral de similitud es 0.75 — ítems con texto muy diferente al almacenado serán filtrados.

### El write falla silenciosamente

```bash
docker compose logs data-normalizer | grep -E "memory|error|warn"
```

El primer uso descarga el modelo ONNX (~65MB) desde HuggingFace — esto puede tardar 10-30s en la primera llamada. Las siguientes son instantáneas (cache en memoria).

### `vector(384)` no existe en la tabla

La migración 22 no se aplicó. Ejecuta:
```bash
psql -U postgres -d procurement_agent \
  -f database/sql/22_agent_memory_vector_dim.sql
```

---

## Checklist de aceptación (Phase 3)

- [ ] `agent_memory_vectors` tiene `vector(384)` con índice HNSW cosine
- [ ] `POST /normalize/memory/write` devuelve `{"stored": true}` en < 2s (tras carga inicial del modelo)
- [ ] `POST /normalize/memory/search` devuelve resultados con `similarity` para ítems similares
- [ ] Al confirmar un pedido en el frontend, aparece `[memory] stored transaction` en logs del orchestrator
- [ ] En la siguiente solicitud de ítem similar, el panel de razonamiento muestra nodo `memory_context`
- [ ] Solicitudes de ítems distintos **no** muestran nodo `memory_context` (umbral 0.75 filtra correctamente)
- [ ] Latencia del enriquecimiento < 5s (timeout configurado en orchestrator)
