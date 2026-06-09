---
tags: [tests, phase-2, real-time, tracking, websocket, kafka, slack, teams, email, e2e]
cssclasses: [procurement-doc, test-doc]
status: "#processed"
related: ["[[real_time_tracking]]", "[[phase2_core_intelligence_transaction_flow]]", "[[event_streaming_kafka]]", "[[communication_slack_teams]]", "[[frontend_react_nextjs]]"]
---

# Phase 2 — Real-Time Tracking E2E Test Guide

> [!info] Prerequisites
> - PostgreSQL local (homebrew) corriendo en `localhost:5432`, esquema aplicado.
> - Docker Desktop activo.
> - `npm` y Node 18+ instalados.
> - Ollama corriendo en el host (`localhost:11434`) con `qwen3:1.7b` cargado.
> - Cuenta Phase Two para el login (las credenciales viven en `frontend/.env.local`).

---

## 1. Setup inicial — levantar el stack y el frontend

Abre **4 terminales** en paralelo. Esto es lo mínimo para ver el flujo en vivo.

### Terminal 1 — Stack completo

```bash
cd /Users/cristianmontiel/Downloads/Infosys/Projects/AgenticAI/Procurement-Agent
docker compose up -d
docker compose ps           # Verifica que TODO esté "Up" o "(healthy)"
docker compose logs -f orchestrator | grep -E "kafka|ws"
```

### Terminal 2 — Frontend (Next.js)

```bash
cd frontend
npm install                 # solo la 1a vez, o si faltan deps (recharts, etc.)
npm run dev                 # → http://localhost:3000
```

### Terminal 3 — Watch del DB en vivo

```bash
psql -h localhost -U cristianmontiel -d procurement_agent
```

Dentro de psql:

```sql
SELECT po_id, beckn_confirm_ref, status, created_at
FROM purchase_orders
ORDER BY created_at DESC LIMIT 3 \watch 0.5
```

(Si `watch` de macOS no está instalado, `psql`'s `\watch 0.5` re-ejecuta el query cada 500ms sin gastar memoria.)

### Terminal 4 — Lista para disparar eventos

Déjala vacía por ahora; la usamos para producir eventos manuales en la sección 3.

---

## 2. Flujo end-to-end desde el frontend

> [!success] Acceptance criterion (`real_time_tracking.md`)
> Dashboard refleja el cambio de estado en **<30 segundos** (en práctica <2s con WebSocket).

### Paso 1 — Crear una orden

1. Abre `http://localhost:3000`.
2. **Login** con Phase Two SSO.
3. En el textarea escribe: `comprar 10 reams de papel A4 para Bangalore`.
4. Click **Parse** → revisa el intent estructurado → **Confirm**.
5. En la pantalla de ofertas, escoge una → **Commit**.
6. Te redirige a `/request/{txn_id}/order` — **anota el `txn_id` de la URL** (necesario en el Paso 3).

### Paso 2 — Verificar que el WebSocket conectó

En el dashboard que se acaba de abrir:

- El componente **StatusPoller** (encima de la timeline) debe mostrar **"🟢 Live · last update X ago"** con un ícono Wifi verde.
- Abre **DevTools → Network → WS** del browser. Debe aparecer una conexión a `ws://localhost:8004/ws/status/{tu_txn_id}` con status `101 Switching Protocols`.
- En Terminal 1 verás:
  ```
  orchestrator-1 | INFO:__main__:[ws] connected txn=<tu_txn> (clients=1)
  ```

**Diagnóstico si NO ves "🟢 Live"** (sino "Polling every 30s"):
- El fallback de polling está activo → el WebSocket no conectó.
- Revisa: `docker compose logs orchestrator | grep kafka` debe mostrar "producer connected" y "consumer subscribed".
- Reinicia con `docker compose restart orchestrator`.

### Paso 3 — Disparar un cambio de estado (3 vías)

Reemplaza `TU_TXN_ID` y `TU_ORDER_ID` por los reales de la orden recién creada.

#### Vía A — Kafka directo

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-producer.sh \
  --topic po.status.changed --bootstrap-server kafka:9092
# Pega y Enter:
{"transaction_id":"TU_TXN_ID","order_id":"TU_ORDER_ID","state":"SHIPPED","po_status":"shipped","source":"manual"}
# Ctrl+D para salir.
```

#### Vía B — Webhook del seller (HMAC-signed)

```bash
TXN="TU_TXN_ID"
ORDER="TU_ORDER_ID"
BODY="{\"transaction_id\":\"$TXN\",\"order_id\":\"$ORDER\",\"beckn_state\":\"SHIPPED\"}"
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "dev-seller-hmac-CHANGE_ME" -binary | base64)
curl -X POST http://localhost:8004/webhooks/seller/status \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -d "$BODY"
```

#### Vía C — Refresh manual / poll Beckn

Click en el botón refresh del `StatusPoller`. Si `sim-bpp` ya cambió el estado, el orchestrator detectará y publicará a Kafka.

#### Vía D — Auto-advance autónomo del BPP (lo más realista, opt-in)

Por default `sim-bpp` NO simula el lifecycle físico — solo responde con `ACTIVE` al `/status`. Para activar un BPP que empuje las transiciones automáticamente como lo haría Amazon Business o Flipkart en producción:

```bash
SIM_BPP_AUTO_ADVANCE=true SIM_BPP_ADVANCE_INTERVAL_SECS=5 \
  docker compose up -d --force-recreate sim-bpp
docker compose logs --tail=3 sim-bpp   # confirma que arrancó
```

Cuando esté activo, **después de cada `/commit`** sim-bpp lanza un task en background que emite, cada `SIM_BPP_ADVANCE_INTERVAL_SECS` segundos:

```
ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED
```

Cada transición ejecuta dos cosas en paralelo:
1. `PATCH http://data-normalizer:8006/normalize/po_status` — actualiza `purchase_orders.status` en PostgreSQL.
2. `produce` al topic Kafka `po.status.changed` — dispara WebSocket broadcast + Slack/Teams/Email.

**Comportamiento esperado desde el frontend:** después de hacer `Commit`, la timeline visual avanza sola sin intervención manual. Con interval=5s, el ciclo completo Confirmed → Delivered tarda ~25 segundos.

> [!warning] Trade-off
> Auto-advance es ideal para demos, pero quitan el control fino para testear casos específicos (ej. "qué pasa si SHIPPED llega después de DELIVERED"). Apágalo (`SIM_BPP_AUTO_ADVANCE=false`) para usar las vías A/B manuales.

**Coexistencia con disparos manuales:** si haces curl `SHIPPED` mientras auto-advance está activo, el orchestrator guarda solo la PRIMERA transición a `shipped` (el guard `if new_state != last_state` previene duplicados). El segundo evento es no-op.

**Cancelación a mitad de flujo:** al hacer `cancel` (vía frontend o el endpoint `/cancel`), sim-bpp también recibe el `cancel` de Beckn y aborta el task del lifecycle para ese order (no seguirá disparando estados después).

### Paso 4 — Verificar la propagación end-to-end

Casi simultáneamente deberías ver:

- **Browser (dashboard):** la timeline avanza al paso "SHIPPED" sin recargar. "last update" se reinicia a "just now".
- **Terminal 1 (logs orchestrator):**
  ```
  [kafka] forwarded state=SHIPPED txn=... to 1 ws client(s)
  ```
- **Terminal 3 (psql watch):** la fila `purchase_orders` correspondiente cambia su `status` a `shipped` y `updated_at` se actualiza.

### Paso 5 — Avanzar a DELIVERED

Repite Paso 3 con `"state":"DELIVERED"` (Vía A) o `"beckn_state":"DELIVERED"` (Vía B).

Verás:
- Timeline pinta "DELIVERED".
- StatusPoller cambia a **"Tracking stopped — order delivered"** (estado terminal).
- El WebSocket se cierra automáticamente (`[ws] disconnected` en logs).

### Paso 6 — Probar las 3 fuentes convergentes

Repite el Paso 3 con cada vía A, B y C en sesiones distintas. **Las 3 producen el mismo update visual en el dashboard** — eso demuestra la convergencia de los 3 streams hacia el canal Kafka `po.status.changed`.

### Paso 7 — Probar el fallback (resiliencia)

```bash
docker compose stop kafka
```

Refresca el dashboard:
- El StatusPoller cambia a **"Polling every 30s"** (modo fallback).
- El sistema sigue funcionando, solo que con latencia de polling.

```bash
docker compose start kafka
```

Refresca de nuevo:
- Vuelve a **"🟢 Live"**.
- El WebSocket se reconecta automáticamente.

---

## 3. Probar las notificaciones Slack / Teams / Email

> [!info] Reglas de fan-out (de `real_time_tracking.md`)
> | Cuando llega `state=…` | Slack | Teams | Email |
> |---|:---:|:---:|:---:|
> | CONFIRMED | ✅ | ✅ | ✅ |
> | SHIPPED | ✅ | ✅ | — |
> | DELIVERED | ✅ | ✅ | ✅ |
> | CANCELLED | ✅ | ✅ | — |
> | (otros) | — | — | — |

### Cómo observar los disparos

```bash
# Terminal 5 — logs del dispatcher en vivo
docker compose logs -f notification-dispatcher
```

Cuando se dispara un canal verás:
```
[slack] sent state=SHIPPED txn=...
[teams] sent state=SHIPPED txn=...
[email] sent to=cris@... state=DELIVERED txn=...
```

### Canal 1 — Slack (≈10 min de setup)

#### Setup en Slack

1. Ve a https://api.slack.com/apps → **Create New App** → **From scratch**.
2. Nombre cualquiera (ej. "Procurement Agent Dev") → escoge tu workspace.
3. Menú izquierdo: **Incoming Webhooks** → toggle **Activate** → ON.
4. Botón **Add New Webhook to Workspace** → escoge un canal (ej. `#general`).
5. Copia el URL: `https://hooks.slack.com/services/T01ABC.../B02DEF.../xyz123...`

#### Configurar y reiniciar el dispatcher

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/...tu-url-completa..."
docker compose up -d --force-recreate notification-dispatcher
docker compose logs --tail=3 notification-dispatcher
# Debe decir: "Channels enabled: ['slack']"
```

#### Test E2E

1. Abre `http://localhost:3000`, crea una orden, llega a `/request/{txn}/order`.
2. Dispara `SHIPPED` (Vía A o B del Paso 3 anterior).
3. **Mira tu canal de Slack** — te llega un mensaje:
   > :truck: **Order status update — SHIPPED**
   > Order: `ord-1` · Transaction: `<txn_id>` · Source: `manual` · Observed at: 2026-…

Si no llega: `docker compose logs notification-dispatcher | grep slack`.

### Canal 2 — Microsoft Teams (≈15-20 min, más enredado)

Microsoft está deprecando los "Office 365 connectors". El camino actual es **Power Automate Workflow**.

#### Setup en Teams

1. Abre Microsoft Teams → ve al canal donde quieres recibir.
2. Menú "**…**" del canal → **Workflows**.
3. Plantilla: **"Post to a channel when a webhook request is received"**.
4. Sigue el wizard. Te quedará un URL tipo `https://prod-XX.westus.logic.azure.com:443/workflows/...`.
5. Copia el URL.

> [!warning] Compatibilidad de Adaptive Cards
> El payload que envía `teams_channel.py` es un Adaptive Card. Si tu Workflow no lo procesa correctamente, simplifica el payload en `services/notification-dispatcher/src/teams_channel.py` a `{"text": "Order status update..."}`.

#### Configurar

```bash
export TEAMS_WEBHOOK_URL="https://prod-XX.westus.logic.azure.com:443/workflows/..."
docker compose up -d --force-recreate notification-dispatcher
# Si ya tenías SLACK_WEBHOOK_URL, ambos canales activos:
# "Channels enabled: ['slack', 'teams']"
```

#### Test

Misma vía que Slack. Dispara `SHIPPED` y observa el canal de Teams.

### Canal 3 — Email (≈15 min con Mailtrap)

**Mailtrap** es un SMTP de testing — captura emails en un inbox virtual, no manda al mundo real. Ideal para dev.

#### Setup en Mailtrap

1. https://mailtrap.io → crea cuenta gratis.
2. **Email Testing → Inboxes → My Sandbox** (viene por default).
3. Tab **SMTP Settings** → escoge `aiosmtplib` del dropdown.
4. Anota: `host` (sandbox.smtp.mailtrap.io), `port` (2525), `username`, `password`.

#### Pre-requisito: la cadena de FKs debe estar completa

El email se resuelve haciendo un JOIN desde `purchase_orders.beckn_confirm_ref` hasta `users.email`. Esa cadena solo se llena al completar `/commit` desde el frontend. Verifica:

```bash
psql -h localhost -U cristianmontiel -d procurement_agent -c "
SELECT po.beckn_confirm_ref AS order_id, u.email
FROM purchase_orders po
JOIN approval_decisions ad   ON ad.approval_id = po.approval_id
JOIN negotiation_outcomes no ON no.negotiation_id = ad.negotiation_id
JOIN scored_offers so        ON so.score_id = no.score_id
JOIN seller_offerings sof    ON sof.offering_id = so.offering_id
JOIN discovery_queries dq    ON dq.query_id = sof.query_id
JOIN beckn_intents bi        ON bi.beckn_intent_id = dq.beckn_intent_id
JOIN parsed_intents pi       ON pi.intent_id = bi.intent_id
JOIN procurement_requests pr ON pr.request_id = pi.request_id
JOIN users u                 ON u.user_id = pr.requester_id
ORDER BY po.created_at DESC LIMIT 5;"
```

Si está vacío: aún no has completado una orden con `/commit`. Si la columna `email` está vacía en `users`, ponle un valor:

```bash
psql -h localhost -U cristianmontiel -d procurement_agent -c \
  "UPDATE users SET email = 'tu-test@example.com' WHERE email IS NULL OR email = '';"
```

#### Configurar el dispatcher

```bash
export SMTP_HOST="sandbox.smtp.mailtrap.io"
export SMTP_PORT=2525
export SMTP_USER="<username de mailtrap>"
export SMTP_PASSWORD="<password de mailtrap>"
export SMTP_FROM="noreply@procurement-agent.local"
docker compose up -d --force-recreate notification-dispatcher
# "Channels enabled: ['email']" (o ['slack', 'teams', 'email'] si tienes todo)
```

#### Test E2E

1. En el frontend, crea una orden y completa `/commit` (esto llena la cadena de FKs).
2. Dispara `DELIVERED` (no SHIPPED — email solo se manda en CONFIRMED/DELIVERED):
   ```bash
   TXN="..."; ORDER="..."
   BODY="{\"transaction_id\":\"$TXN\",\"order_id\":\"$ORDER\",\"beckn_state\":\"DELIVERED\"}"
   SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "dev-seller-hmac-CHANGE_ME" -binary | base64)
   curl -X POST http://localhost:8004/webhooks/seller/status \
     -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
   ```
3. Abre tu inbox de Mailtrap → debe aparecer el email HTML con subject `Order DELIVERED — ord-X`.

#### Diagnóstico

```bash
docker compose logs notification-dispatcher | grep -E "email|recipient"
# "[email] sent to=..."           → OK
# "[email] no recipient found..."  → la cadena de FKs falló (revisa la query del JOIN)
```

### Probar las 3 notificaciones en una sola corrida

Setea las 3 envs (Slack + Teams + Mailtrap) y luego:

1. Crear orden → `/request/{txn}/order`.
2. Disparar `CONFIRMED`: llegan **Slack + Teams + Email**.
3. Disparar `SHIPPED`: llegan **Slack + Teams**.
4. Disparar `DELIVERED`: llegan **Slack + Teams + Email** (timeline marca terminal).

### Atajo sin configurar nada externo: webhook.site

Para verificar que el dispatcher emite POSTs sin configurar Slack/Teams/Mailtrap:

```bash
# 1. Abre https://webhook.site → te da un URL único.
export SLACK_WEBHOOK_URL="https://webhook.site/tu-id-único"
export TEAMS_WEBHOOK_URL="https://webhook.site/otro-id-único"  # otra pestaña
docker compose up -d --force-recreate notification-dispatcher
# Dispara estados desde el frontend → ves los POST en webhook.site en vivo.
```

---

## 4. Comandos rápidos de referencia

### Iniciar todo desde cero

```bash
docker compose up -d --build
cd frontend && npm run dev
```

### Reiniciar solo el dispatcher (sin tocar lo demás)

```bash
docker compose up -d --force-recreate notification-dispatcher
docker compose logs -f notification-dispatcher
```

### Watch en vivo del DB

```bash
# psql interactivo
psql -h localhost -U cristianmontiel -d procurement_agent
# Dentro:
SELECT * FROM purchase_orders ORDER BY created_at DESC LIMIT 3 \watch 0.5
```

### Producir un evento desde Kafka

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-producer.sh \
  --topic po.status.changed --bootstrap-server kafka:9092
```

### Webhook del seller con HMAC

```bash
BODY='{"transaction_id":"T","order_id":"O","beckn_state":"SHIPPED"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "dev-seller-hmac-CHANGE_ME" -binary | base64)
curl -X POST http://localhost:8004/webhooks/seller/status \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
```

### Correr los tests unitarios

```bash
.venv-test/bin/python -m pytest \
  services/orchestrator/tests/test_realtime_tracking.py \
  services/notification-dispatcher/tests/ -v
```

---

## 5. Troubleshooting

| Síntoma | Causa probable | Fix |
|---|---|---|
| StatusPoller dice "Polling every 30s" | WebSocket no conectó | `docker compose restart orchestrator` |
| `purchase_orders` no se llena después de `/commit` | Sesión perdida tras restart del orchestrator | Hacer `/compare` + `/commit` sin restart en medio |
| `PATCH /normalize/po_status` devuelve 405 | Bug viejo (método incorrecto) | Verificar que `_persist` se llame con `method="PATCH"` |
| `[email] no recipient found` | Cadena FK rota o `users.email` vacío | `UPDATE users SET email = '...' WHERE email IS NULL` |
| `Module not found: recharts` en `npm run dev` | `node_modules` desactualizado | `cd frontend && npm install` |
| Notificaciones no llegan | Webhook URL mal o channel deshabilitado | `docker compose logs notification-dispatcher \| grep Channels` |
| Auto-advance no dispara después de `/commit` | El flag está en `false` (default) | `SIM_BPP_AUTO_ADVANCE=true docker compose up -d --force-recreate sim-bpp` |
| Auto-advance avanza demasiado rápido para demos | Interval por defecto es 5s | Subir a 10-15s: `SIM_BPP_ADVANCE_INTERVAL_SECS=10` |

---

*Cubre el Phase 2 milestone: real_time_tracking | Cris. Validation contra `sim-bpp` (= Beckn sandbox local) cumple el criterio "Both `/status` polling and webhook push paths validated".*
