---
tags: [tests, phase-2, real-time, tracking, websocket, kafka, slack, teams, email, sim-bpp, e2e]
cssclasses: [procurement-doc, test-doc]
status: "#processed"
related: ["[[real_time_tracking]]", "[[phase2_core_intelligence_transaction_flow]]", "[[event_streaming_kafka]]", "[[communication_slack_teams]]", "[[frontend_react_nextjs]]"]
---

# Phase 2 — Real-Time Tracking E2E Test Guide

> [!info] Qué cubre este documento
> Cómo probar end-to-end el componente `real_time_tracking` (Phase 2 milestone)
> desde el frontend: WebSocket, Kafka, persistencia en `purchase_orders`,
> notificaciones Slack/Teams/Email y auto-advance del BPP simulado.
>
> El criterio de aceptación del milestone es: *Dashboard refleja cualquier cambio
> de estado en menos de 30 segundos*. En la práctica logramos **<2 s** vía
> WebSocket cuando Kafka está sano, y un fallback a polling de 30 s si Kafka cae.

> [!success] Prerrequisitos
> - PostgreSQL local (Homebrew) corriendo en `localhost:5432`, esquema aplicado
>   (ver `database/README.md` para el setup inicial).
> - Docker Desktop activo.
> - Node 18+ y `npm`.
> - Ollama corriendo en el host (`localhost:11434`) con `qwen3:1.7b` cargado.
> - Cuenta Phase Two configurada en `frontend/.env.local` (`KEYCLOAK_*` vars).
> - Python 3.12+ con un venv local (`.venv-test/`) para los tests unitarios.

---

## 1. Setup inicial — levantar el stack y el frontend

Abre **4 terminales** en paralelo. Esto es lo mínimo para ver el flujo en vivo;
las terminales 3 y 4 son observadores, no es necesario teclear nada en ellas
hasta el paso correspondiente.

### Terminal 1 — Stack completo

```bash
cd /Users/cristianmontiel/Downloads/Infosys/Projects/AgenticAI/Procurement-Agent
docker compose up -d
docker compose ps           # todo debe estar "Up" o "(healthy)"
docker compose logs -f orchestrator | grep -E "kafka|ws"
```

Esa última línea te queda corriendo: te muestra cuándo el orchestrator levanta el productor Kafka, el consumidor, y cada conexión / broadcast de WebSocket.

### Terminal 2 — Frontend (Next.js)

```bash
cd frontend
npm install                 # la 1ª vez o si faltan deps (recharts, etc.)
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

> El comando `watch` GNU no viene con macOS. `psql`'s `\watch 0.5` re-ejecuta el query cada 500 ms manteniendo la conexión abierta — más eficiente.

### Terminal 4 — Para disparar eventos manualmente

Déjala vacía por ahora. La usamos en el Paso 3 (vías A, B) y en pruebas avanzadas.

---

## 2. Flujo end-to-end desde el frontend

> [!success] Criterio de aceptación (`real_time_tracking.md`)
> Dashboard refleja el cambio de estado en **<30 segundos**. Con WebSocket sano: típicamente **<2 s**.

### Paso 1 — Crear una orden

1. Abre `http://localhost:3000`.
2. **Login** con Phase Two SSO.
3. En el textarea escribe: `comprar 10 reams de papel A4 para Bangalore`.
4. Click **Parse** → revisa el intent estructurado → **Confirm**.
5. En la pantalla de ofertas, escoge una → **Commit**.
6. Te redirige a `/request/{txn_id}/order`. **Anota el `txn_id` de la URL** y el `order_id` que ves en la respuesta del commit (también lo puedes leer en Terminal 3 — es el `beckn_confirm_ref` de la fila más reciente en `purchase_orders`).

### Paso 2 — Verificar que el WebSocket conectó

En el dashboard recién cargado:

- El componente **StatusPoller** (encima de la timeline) muestra **"🟢 Live · last update X ago"** con un ícono Wifi verde.
- Abre **DevTools → Network → WS** del browser. Debe aparecer una conexión a `ws://localhost:8004/ws/status/{tu_txn_id}` con status `101 Switching Protocols`.
- En Terminal 1 verás:
  ```
  orchestrator-1 | INFO:__main__:[ws] connected txn=<tu_txn> (clients=1)
  ```

**Si NO ves "🟢 Live" sino "Polling every 30s"**:
- El fallback de polling está activo → el WebSocket no conectó.
- `docker compose logs orchestrator | grep kafka` debe mostrar "producer connected" y "consumer subscribed". Si no aparecen, Kafka está caído.
- `docker compose restart orchestrator` y refresca la página.

### Paso 3 — Disparar un cambio de estado (4 vías)

Reemplaza `TU_TXN_ID` y `TU_ORDER_ID` por los reales de la orden recién creada. Cada vía produce el mismo efecto final: `purchase_orders.status` cambia + dashboard avanza + notificaciones disparan según las reglas.

#### Vía A — Producir directamente a Kafka

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-producer.sh \
  --topic po.status.changed --bootstrap-server kafka:9092
# Pega y Enter:
{"transaction_id":"TU_TXN_ID","order_id":"TU_ORDER_ID","state":"SHIPPED","po_status":"shipped","source":"manual"}
# Ctrl+D para salir.
```

Útil para pruebas controladas donde necesitas un payload exacto.

#### Vía B — Webhook del seller (HMAC-signed)

Simula que un BPP real toca la puerta del orchestrator:

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

Esta vía ejercita la validación HMAC + el camino completo persist → audit → publish.

#### Vía C — Refresh manual / poll Beckn

Click en el botón refresh del `StatusPoller`. El orchestrator hace `GET /status/{txn}/{order}` contra `sim-bpp`. **Limitación:** sim-bpp por defecto siempre devuelve `ACTIVE` (estado contractual, no logístico), así que esta vía sola no avanza la timeline más allá de `confirmed`. Para que esta vía sirva, activa la Vía D abajo.

#### Vía D — Auto-advance autónomo del BPP (opt-in, lo más realista)

Por default `sim-bpp` no simula el lifecycle físico. Para activar un BPP que empuje las transiciones autónomamente (como Amazon Business o Flipkart):

```bash
SIM_BPP_AUTO_ADVANCE=true SIM_BPP_ADVANCE_INTERVAL_SECS=5 \
  docker compose up -d --force-recreate sim-bpp
docker compose logs --tail=5 sim-bpp   # confirma que arrancó
```

Cuando esté activo, **después de cada `/commit`** sim-bpp lanza un task que emite, cada `SIM_BPP_ADVANCE_INTERVAL_SECS` segundos:

```
ACCEPTED → PACKED → SHIPPED → OUT_FOR_DELIVERY → DELIVERED
```

Cada transición hace dos cosas en paralelo:
1. `PATCH http://data-normalizer:8006/normalize/po_status` — actualiza `purchase_orders.status`.
2. Produce al topic Kafka `po.status.changed` — dispara WebSocket broadcast + Slack/Teams/Email.

**Comportamiento esperado en el frontend:** tras hacer Commit, la timeline avanza sola. Con interval=5 s, el ciclo Confirmed → Delivered tarda ≈25 s. El Paso 8 abajo es el checklist específico para validar esta vía.

> [!warning] Trade-off
> Auto-advance es ideal para demos pero te quita control fino para casos específicos (p. ej. "qué pasa si SHIPPED llega después de DELIVERED"). Apágalo (`SIM_BPP_AUTO_ADVANCE=false`) para usar las vías A/B manuales.

**Coexistencia con disparos manuales:** si haces curl con `SHIPPED` mientras auto-advance ya pasó a `shipped`, el orchestrator no persiste de nuevo (el guard `if new_state != last_state` previene duplicados). El segundo evento es no-op.

**Cancelación a mitad de flujo:** si llamas a `/cancel` (vía frontend o el endpoint directo), sim-bpp también recibe el `cancel` Beckn y aborta el task del lifecycle. No seguirá disparando estados después.

### Paso 4 — Verificar la propagación end-to-end

Casi simultáneamente al disparo (de cualquiera de las 4 vías) deberías ver:

- **Browser (dashboard):** la timeline avanza al paso correspondiente sin recargar. "last update" se reinicia a "just now".
- **Terminal 1 (logs orchestrator):**
  ```
  [kafka] forwarded state=SHIPPED txn=... to 1 ws client(s)
  ```
- **Terminal 3 (psql `\watch`):** la fila `purchase_orders` correspondiente cambia su `status` y `updated_at` se actualiza al timestamp de ahora.

### Paso 5 — Avanzar hasta DELIVERED

Repite Paso 3 con `"state":"DELIVERED"` (Vía A) o `"beckn_state":"DELIVERED"` (Vía B). Con auto-advance (Vía D) ya llega solo después de unos segundos.

Cuando llega a DELIVERED:
- Timeline pinta el último paso.
- StatusPoller cambia a **"Tracking stopped — order delivered"** (estado terminal).
- El WebSocket se cierra solo (`[ws] disconnected` en logs).

### Paso 6 — Probar las 4 fuentes convergentes

Crea órdenes distintas y dispara cada vía (A, B, C, D) en sesiones separadas. **Las 4 producen el mismo update visual en el dashboard** — eso demuestra la convergencia de los 4 streams hacia el canal Kafka `po.status.changed`. Es la propiedad arquitectónica clave del componente: cualquier productor nuevo (un ERP externo, un sistema de tracking de paquetería, etc.) se integra publicando al mismo topic sin tocar nada del frontend ni del consumer.

### Paso 7 — Probar el fallback (resiliencia)

Verifica que el sistema sobrevive a una caída de Kafka:

```bash
docker compose stop kafka
```

Refresca el dashboard:
- StatusPoller cambia a **"Polling every 30s"** (modo fallback HTTP).
- El sistema sigue funcionando, solo con latencia de polling.

```bash
docker compose start kafka
```

Refresca de nuevo:
- Vuelve a **"🟢 Live"**.
- El WebSocket se reconecta automáticamente.

### Paso 8 — Validar específicamente auto-advance (Vía D)

Si activaste auto-advance en el Paso 3 Vía D, este checklist confirma que **TODA** la cadena funciona end-to-end:

1. **Confirma el arranque con el flag activo:**
   ```bash
   SIM_BPP_AUTO_ADVANCE=true SIM_BPP_ADVANCE_INTERVAL_SECS=5 \
     docker compose up -d --force-recreate sim-bpp
   docker compose logs --tail=10 sim-bpp
   
   SIM_BPP_AUTO_ADVANCE=true docker compose up -d --force-recreate sim-bpp
   ```
2. Debes ver `sim-bpp starting on :3002`. (El flag se confirma indirectamente cuando aparezca un log "auto-advance: started" después del primer `/commit`.)

3. **Crea una orden completa** desde el frontend (Login → Parse → Confirm → Commit). Anota `order_id`.

4. **En Terminal 3 (psql watch)** observa cómo `purchase_orders.status` cambia solo:
   | Aproximadamente | Status esperado | Beckn state interno |
   |---|---|---|
   | `/commit` retorna | `pending` | (sin lifecycle aún) |
   | T+5 s | `confirmed` | ACCEPTED |
   | T+10 s | `confirmed` | PACKED |
   | T+15 s | `shipped` | SHIPPED |
   | T+20 s | `shipped` | OUT_FOR_DELIVERY |
   | T+25 s | `delivered` | DELIVERED — terminal |

5. **En Terminal 1 / logs sim-bpp**, durante esos ~25 s verás:
   ```
   sim-bpp | auto-advance: started order=<ORDER> txn=<TXN> interval=5s
   sim-bpp | kafka published state=ACCEPTED order=<ORDER>
   sim-bpp | auto-advance: order=<ORDER> → ACCEPTED (confirmed)
   sim-bpp | kafka published state=PACKED order=<ORDER>
   sim-bpp | auto-advance: order=<ORDER> → PACKED (confirmed)
   …
   sim-bpp | auto-advance: order=<ORDER> → DELIVERED (delivered)
   ```

6. **En los logs del orchestrator** las 5 reenvíos a WebSocket:
   ```
   orchestrator-1 | [kafka] forwarded state=ACCEPTED txn=... to 1 ws client(s)
   orchestrator-1 | [kafka] forwarded state=PACKED txn=... to 1 ws client(s)
   …
   ```

7. **En el browser**, la timeline avanza paso a paso sin que toques nada y termina en "Tracking stopped — order delivered".

8. **Probar cancelación mid-flow:**
   - Crea una nueva orden y, dentro de los primeros ~10 s post-Commit, llama al endpoint `/cancel`:
     ```bash
     curl -X PATCH http://localhost:8004/cancel \
       -H "Content-Type: application/json" \
       -d "{\"request_id\":\"<REQUEST_ID>\"}"
     ```
   - En los logs de sim-bpp verás `auto-advance: cancelled order=<ORDER>`.
   - El status final en `purchase_orders` no avanza más allá del estado donde estaba al momento del cancel (el orchestrator marca `cancelled` por su lado en `procurement_requests`).

> [!check] Checklist resumido del Paso 8
> - [ ] sim-bpp arrancó con `SIM_BPP_AUTO_ADVANCE=true`
> - [ ] 5 estados visibles en la columna `purchase_orders.status` durante ~25 s
> - [ ] 5 líneas "auto-advance: order=… → STATE" en logs de sim-bpp
> - [ ] 5 líneas "[kafka] forwarded state=…" en logs del orchestrator
> - [ ] Timeline en el browser llega a DELIVERED sin intervención manual
> - [ ] /cancel mid-flow aborta correctamente (log "cancelled" + lifecycle se detiene)

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
6. Entrar para recibir las notificaciones: https://app.slack.com/client/T0BEATQ7VNZ/C0BEHUUM7PE?entry_point=redirect_flow

#### Configurar y reiniciar el dispatcher

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/...tu-url-completa..."
docker compose up -d --force-recreate notification-dispatcher
docker compose logs --tail=3 notification-dispatcher
# Debe decir: "Channels enabled: ['slack']"
```

#### Test E2E

1. Abre `http://localhost:3000`, crea una orden, llega a `/request/{txn}/order`.
2. Dispara `SHIPPED` (Vía A o B del Paso 3, o espera al auto-advance de Vía D).
3. **Mira tu canal de Slack** — te llega un mensaje con formato Block Kit:
   > :truck: **Order status update — SHIPPED**
   > Order: `<order_id>` · Transaction: `<txn_id>` · Source: `manual` · Observed at: 2026-…

Diagnóstico si no llega: `docker compose logs notification-dispatcher | grep slack`.

### Canal 2 — Microsoft Teams (≈15-20 min)

Microsoft está deprecando los "Office 365 connectors" tradicionales. El camino actual recomendado es **Power Automate Workflow**.

#### Setup en Teams

1. Abre Microsoft Teams → ve al canal donde quieres recibir notificaciones.
2. Menú "**…**" del canal → **Workflows**.
3. Plantilla: **"Post to a channel when a webhook request is received"**.
4. Sigue el wizard. Te quedará un URL tipo `https://prod-XX.westus.logic.azure.com:443/workflows/...`.
5. Copia el URL.

> [!warning] Compatibilidad de Adaptive Cards
> El payload que envía `teams_channel.py` es un Adaptive Card v1.4. Si tu Workflow no lo procesa correctamente, edita `services/notification-dispatcher/src/teams_channel.py` y simplifica el payload a `{"text": "Order status update..."}`.

#### Configurar

```bash
export TEAMS_WEBHOOK_URL="https://prod-XX.westus.logic.azure.com:443/workflows/..."
docker compose up -d --force-recreate notification-dispatcher
# Con Slack ya configurado, ambos canales activos:
# "Channels enabled: ['slack', 'teams']"
```

#### Test

Misma vía que Slack. Dispara `SHIPPED` (manual o esperando auto-advance) y observa el canal de Teams.

### Canal 3 — Email (≈15 min con Mailtrap)

**Mailtrap** es un servicio SMTP de testing — captura emails en un inbox virtual, **no manda al mundo real**. Ideal para dev.

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

Si está vacío: aún no has completado una orden con `/commit`. Si la columna `email` aparece NULL/vacía, ponle un valor de prueba:

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
# Confirma: "Channels enabled: ['email']" (o ['slack', 'teams', 'email'] si tienes todo)
```

#### Test E2E

1. En el frontend, crea una orden y completa `/commit` (esto llena la cadena de FKs).
2. Dispara `DELIVERED` (no SHIPPED — email solo se manda en CONFIRMED y DELIVERED):
   ```bash
   TXN="..."; ORDER="..."
   BODY="{\"transaction_id\":\"$TXN\",\"order_id\":\"$ORDER\",\"beckn_state\":\"DELIVERED\"}"
   SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "dev-seller-hmac-CHANGE_ME" -binary | base64)
   curl -X POST http://localhost:8004/webhooks/seller/status \
     -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
   ```
3. Abre tu inbox de Mailtrap → debe aparecer el email HTML con subject `Order DELIVERED — <order_id>`.

#### Diagnóstico

```bash
docker compose logs notification-dispatcher | grep -E "email|recipient"
# "[email] sent to=..."           → OK
# "[email] no recipient found..."  → la cadena de FKs falló (verifica con el JOIN)
```

### Probar las 3 notificaciones en una sola corrida

Setea las 3 envs (Slack + Teams + Mailtrap), levanta sim-bpp con auto-advance, y crea una orden. En ~25 s verás:

1. `CONFIRMED` (estado inicial al confirmar): llegan **Slack + Teams + Email**.
2. `SHIPPED` (auto-advance lo dispara): llegan **Slack + Teams**.
3. `DELIVERED` (auto-advance al final): llegan **Slack + Teams + Email** (timeline marca terminal).

### Atajo sin configurar nada externo: webhook.site

Para verificar que el dispatcher emite POSTs sin crear cuentas Slack/Teams/Mailtrap:

```bash
# Abre https://webhook.site → te da un URL único por pestaña.
export SLACK_WEBHOOK_URL="https://webhook.site/tu-id-único"
export TEAMS_WEBHOOK_URL="https://webhook.site/otro-id-único"
docker compose up -d --force-recreate notification-dispatcher
# Dispara estados desde el frontend → ves los POSTs en webhook.site en vivo.
```

---
## 4. Comandos rápidos de referencia

### Iniciar todo desde cero

```bash
docker compose up -d --build
cd frontend && npm run dev
```

### Iniciar con auto-advance activo (modo demo)

```bash
SIM_BPP_AUTO_ADVANCE=true SIM_BPP_ADVANCE_INTERVAL_SECS=5 \
  docker compose up -d --force-recreate sim-bpp
```

### Reiniciar solo el dispatcher

```bash
docker compose up -d --force-recreate notification-dispatcher
docker compose logs -f notification-dispatcher
```

### Watch en vivo del DB

```bash
psql -h localhost -U cristianmontiel -d procurement_agent
# Dentro:
SELECT po_id, beckn_confirm_ref, status, created_at FROM purchase_orders
ORDER BY created_at DESC LIMIT 3 \watch 0.5
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

### Cancelar una orden a mitad de flujo

```bash
curl -X PATCH http://localhost:8004/cancel \
  -H "Content-Type: application/json" \
  -d '{"request_id":"<REQUEST_ID>"}'
```
