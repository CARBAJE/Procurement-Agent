# Diagramas de Secuencia — Procurement Agent Frontend


---

## 1. Flujo General (Overview)

Muestra todos los componentes del sistema y cómo se encadenan en el flujo completo de una solicitud de compra.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant LF as LoginForm<br/>(React)
    participant NA as NextAuth<br/>(next-auth)
    participant PF as ProcurementForm<br/>(React)
    participant NX as Next.js API Routes<br/>(servidor)
    participant IP as IntentParser<br/>(FastAPI :8001)
    participant BAP as BAP Server<br/>(aiohttp :8000)
    participant ONIX as ONIX Adapter<br/>(Go :8081)

    U->>LF: Ingresa credenciales
    LF->>NA: signIn(email, password)
    NA-->>LF: JWT con rol (requester/approver/admin)
    LF-->>U: Redirige a /dashboard

    U->>PF: Escribe query en lenguaje natural
    PF->>NX: POST /api/procurement/parse { query }
    NX->>IP: POST /parse { query }
    IP-->>NX: ParseResult { beckn_intent, confidence }
    NX-->>PF: ParseResult
    PF-->>U: Muestra IntentPreview (Paso 2)

    U->>PF: Confirma intent
    PF->>NX: POST /api/procurement/compare { beckn_intent }
    NX->>BAP: POST /compare
    BAP->>BAP: arun_compare() → store state by txn_id
    BAP->>ONIX: POST /bap/caller/discover
    ONIX-->>BAP: on_discover callback
    BAP-->>NX: { txn_id, offerings, scoring, reasoning_steps }
    NX-->>PF: ComparisonResult
    PF->>PF: router.push(/request/[txn]/compare)
    PF-->>U: Muestra tabla comparativa

    U->>PF: Selecciona oferta y click "Proceder"
    PF->>NX: POST /api/procurement/commit { txn_id, chosen_item_id }
    NX->>BAP: POST /commit
    BAP->>BAP: arun_commit() → select + init + confirm
    BAP->>ONIX: POST /bap/caller/{select,init,confirm}
    ONIX-->>BAP: on_select, on_init, on_confirm
    BAP-->>NX: { order_id, order_state, payment_terms }
    NX-->>PF: CommitResult
    PF->>PF: router.push(/request/[txn]/order)
    PF-->>U: Muestra orden confirmada + timeline

    loop every 30 s
        PF->>NX: GET /api/procurement/status/{txn}/{order}
        NX->>BAP: GET /status/{txn}/{order}
        BAP->>ONIX: POST /bap/caller/status
        ONIX-->>BAP: on_status { state }
        BAP-->>PF: StatusSnapshot { state, observed_at }
    end
```

---

## 2. Autenticación (SSO Stub)

Detalle del flujo de login con NextAuth usando el proveedor Credentials (stub de Keycloak).

```mermaid
sequenceDiagram
    actor U as Usuario
    participant LF as LoginForm.tsx
    participant NA as NextAuth<br/>/api/auth/[...nextauth]
    participant AUTH as auth.ts<br/>(authOptions)
    participant S as Session (JWT)

    U->>LF: Click en usuario demo<br/>("Priya Sharma")
    LF->>LF: fillDemo(email, password)
    U->>LF: Click "Entrar"
    LF->>NA: signIn("credentials",<br/>{ email, password, redirect: false })
    NA->>AUTH: authorize(credentials)
    AUTH->>AUTH: Busca email en STUB_USERS[]<br/>Verifica STUB_PASSWORDS[email]

    alt Credenciales correctas
        AUTH-->>NA: StubUser { id, name, email, role }
        NA->>S: jwt() → agrega token.role = "requester"
        NA->>S: session() → agrega session.user.role
        NA-->>LF: { ok: true }
        LF->>LF: router.push("/dashboard")
        LF-->>U: Redirige a Dashboard
    else Credenciales incorrectas
        AUTH-->>NA: null
        NA-->>LF: { error: "CredentialsSignin" }
        LF-->>U: Muestra error
    end
```

---

## 3. Parseo de Intent (NL → BecknIntent)

Detalle de cómo la query en lenguaje natural se convierte en un `BecknIntent` estructurado.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant PF as ProcurementForm.tsx
    participant API as api.ts
    participant PR as parse/route.ts<br/>(Next.js API)
    participant IP as IntentParser<br/>(FastAPI :8001)
    participant OL as Ollama<br/>(qwen3:8b / qwen3:1.7b)
    participant IV as IntentPreview.tsx

    U->>PF: Submit form con query
    PF->>PF: handleParse(e)<br/>e.preventDefault()<br/>setLoading(true)
    PF->>API: parseIntent(query)
    API->>PR: axios.POST /api/procurement/parse<br/>{ query }

    PR->>PR: getServerSession(authOptions)<br/>Verifica sesión activa

    alt Sesión válida
        PR->>IP: axios.POST http://127.0.0.1:8000/parse<br/>{ query }
        IP->>IP: Clasifica complejidad<br/>(len > 120 o ≥ 2 números → qwen3:8b)
        IP->>OL: Prompt con query
        OL-->>IP: JSON estructurado
        IP-->>PR: ParseResult {<br/>  intent: "PurchaseOrder",<br/>  confidence: 0.8,<br/>  beckn_intent: { item, quantity,<br/>    delivery_timeline, ... },<br/>  routed_to: "qwen3:1.7b"<br/>}
        PR-->>API: ParseResult
        API-->>PF: ParseResult
        PF->>PF: setParseResult(result)<br/>setStep("preview")
        PF->>IV: Renderiza IntentPreview
        IV-->>U: Muestra intent interpretado<br/>con % confianza
    else IntentParser 5xx (Ollama OOM, etc.)
        IP-->>PR: HTTP 500 { error, detail }
        PR-->>API: forwarded 500 (no silent mock)
        API-->>PF: axios throws
        PF->>PF: setError(detail)
        PF-->>U: Muestra error real en UI<br/>(p.ej. "memory layout cannot be allocated")
    else BAP server caído
        PR-->>API: 502 { error: "IntentParser unreachable" }
        API-->>PF: axios throws
        PF-->>U: Muestra "Start the BAP server..."
    end
```

---

## 4. Compare — Con ONIX (Red Beckn Real)

Flujo de comparación cuando el Docker stack está corriendo. El endpoint `/compare` ejecuta `arun_compare()` (parse_intent + discover + rank_and_select), guarda el estado en `TransactionSessionStore`, y devuelve las offerings con scoring + reasoning trace.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant PF as ProcurementForm.tsx
    participant CR as compare/route.ts<br/>(Next.js API)
    participant BAP as BAP server.py<br/>(:8000)
    participant AG as ProcurementAgent
    participant SS as TransactionSessionStore
    participant BC as BecknClient
    participant CC as CallbackCollector
    participant ONIX as ONIX Adapter<br/>(Go :8081)

    U->>PF: Click "Compare offers"
    PF->>PF: handleConfirm()<br/>Toma beckn_intent del parseResult
    PF->>CR: POST /api/procurement/compare<br/>{ BecknIntent }
    CR->>CR: getServerSession() — verifica auth
    CR->>BAP: axios.POST http://127.0.0.1:8000/compare

    BAP->>AG: arun_compare(intent)
    Note over AG: build_compare_graph:<br/>parse_intent → discover →<br/>rank_and_select → present_results
    AG->>BC: discover_async(intent, collector)
    BC->>CC: register(txn_id, "on_discover")
    BC->>ONIX: POST /bap/caller/discover
    ONIX-->>BC: ACK
    ONIX->>BAP: POST /bap/receiver/on_discover<br/>{ catalogs: [...6 offerings] }
    BC->>CC: collect → DiscoverResponse
    AG->>AG: rank_and_select: min(price)
    AG-->>BAP: state { offerings, selected, reasoning_steps }
    BAP->>SS: session_store.put(txn_id, state)
    BAP-->>CR: { txn_id, offerings, scoring, reasoning_steps, status: "live" }
    CR-->>PF: ComparisonResult

    PF->>PF: saveSession(txn_id, { intent, comparison })<br/>router.push(/request/[txn]/compare)
    PF-->>U: Redirige a CompareView<br/>(tabla comparativa + scoring panel)
```

---

## 5. Commit — Usuario confirma y se ejecuta la transacción

Después de la comparación, el usuario elige una oferta y hace `/commit`. El BAP ejecuta `arun_commit()` (send_select + send_init + send_confirm) y devuelve el `order_id` real del BPP.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant CV as CompareView.tsx
    participant DLG as ConfirmCommitDialog
    participant CM as commit/route.ts
    participant BAP as BAP server.py
    participant AG as ProcurementAgent
    participant SS as TransactionSessionStore
    participant BC as BecknClient
    participant ONIX as ONIX Adapter

    U->>CV: Click "Proceed with selection"
    alt Elige la oferta recomendada
        CV->>CM: POST /api/procurement/commit<br/>{ txn_id, chosen_item_id }
    else Elige una alternativa
        CV->>DLG: Abre dialog con diff<br/>(precio / ETA / rating)
        U->>DLG: Click "Confirm order"
        DLG->>CM: POST /api/procurement/commit<br/>{ txn_id, chosen_item_id }
    end

    CM->>BAP: axios.POST /commit
    BAP->>SS: session_store.get(txn_id)
    Note over BAP: state["selected"] = chosen offering
    BAP->>AG: arun_commit(state)

    Note over AG: build_commit_graph:<br/>send_select → send_init →<br/>send_confirm → present_results

    AG->>BC: select(items, txn, bpp)
    BC->>ONIX: POST /bap/caller/select (v2.1 Contract)
    ONIX-->>BC: ACK
    ONIX->>BAP: on_select callback

    AG->>BC: init(items, billing, fulfillment, ...)
    BC->>ONIX: POST /bap/caller/init<br/>(participants[buyer] + performance[])
    ONIX-->>BC: ACK
    ONIX->>BAP: on_init { settlements, consideration }
    BC-->>AG: InitResponse { payment_terms, quote_total }

    AG->>BC: confirm(items, payment_terms, ...)
    BC->>ONIX: POST /bap/caller/confirm<br/>(settlements + status.code=ACTIVE)
    ONIX-->>BC: ACK
    ONIX->>BAP: on_confirm { contract.id, status }
    BC-->>AG: ConfirmResponse { order_id, state=CREATED }

    AG-->>BAP: final state { order_id, order_state, payment_terms }
    BAP->>SS: session_store.put(txn_id, final_state)
    BAP-->>CM: { order_id, order_state, payment_terms, reasoning_steps }
    CM-->>CV: CommitResult
    CV->>CV: patchSession(txn_id, { commit: result })<br/>router.push(/request/[txn]/order)
    CV-->>U: Redirige a OrderView<br/>(summary + timeline + status poller)
```

---

## 6. Status polling — Después de la orden confirmada

El `StatusPoller.tsx` hace un GET cada 30s. El servidor reconstruye `items` desde la sesión (la v2.1 Contract schema requiere `commitments` en todos los mensajes, también `/status`).

```mermaid
sequenceDiagram
    participant SP as StatusPoller.tsx
    participant ST as status/route.ts
    participant BAP as BAP server.py
    participant SS as TransactionSessionStore
    participant AG as ProcurementAgent
    participant ONIX as ONIX Adapter

    loop every 30 s<br/>(until state ∈ {DELIVERED, CANCELLED})
        SP->>ST: GET /api/procurement/status/{txn}/{order}
        ST->>BAP: GET /status/{txn}/{order}

        BAP->>SS: session_store.get(txn) → { selected, intent }
        Note over BAP: Rebuild SelectedItem from<br/>session to satisfy v2.1<br/>Contract.commitments requirement

        BAP->>AG: get_status(txn, order_id, bpp_id, bpp_uri, items)
        AG->>ONIX: POST /bap/caller/status<br/>{ message.contract: { id, commitments } }
        ONIX-->>AG: ACK
        ONIX->>BAP: on_status { contract.status.code }
        AG-->>BAP: StatusResponse { state, fulfillment_eta, tracking_url }
        BAP-->>ST: StatusSnapshot { state, observed_at, status: "live" }
        ST-->>SP: StatusSnapshot
        SP->>SP: onUpdate(snapshot)<br/>setState(snap.state)
    end
```

---

## 7. Fallback — ONIX / Docker offline

Todos los endpoints `/compare`, `/commit`, `/status` caen a mock fallback si ONIX falla — así la UI funciona standalone para demos. Badge en la UI: "Local Catalog" en vez de "Live Beckn Network".

```mermaid
sequenceDiagram
    participant CV as Frontend
    participant BAP as BAP server.py
    participant BC as BecknClient
    participant ONIX as ONIX<br/>(down)

    CV->>BAP: POST /compare
    BAP->>BC: discover_async(intent, timeout=10s)
    BC->>ONIX: POST /bap/caller/discover
    ONIX--xBC: ECONNREFUSED

    Note over BC,BAP: Exception captured

    BAP->>BAP: _mock_compare_response()<br/>• 6 offerings del _LOCAL_CATALOG<br/>• synthetic reasoning_steps<br/>• recommended = min(price)
    BAP-->>CV: { offerings, scoring, status: "mock" }
    CV-->>CV: Badge azul → gris<br/>("Local Catalog")
```

El mismo patrón aplica a `/commit` (`_mock_commit_response` → genera `mock-order-<hex>`) y `/status` (echo del último estado almacenado).

---

## 6. Protección de Rutas (AuthGuard)

Cómo Next.js protege las páginas y API routes para usuarios no autenticados.

```mermaid
sequenceDiagram
    actor U as Usuario (no autenticado)
    participant NX as Next.js Router
    participant PG as dashboard/page.tsx<br/>(Server Component)
    participant NA as getServerSession()
    participant LG as /login

    U->>NX: GET /dashboard
    NX->>PG: Ejecuta Server Component
    PG->>NA: getServerSession(authOptions)
    NA-->>PG: null (sin sesión)
    PG->>NX: redirect("/login")
    NX-->>U: 307 → /login

    Note over U,LG: Usuario hace login (ver Diagrama 2)

    U->>NX: GET /dashboard (con sesión)
    NX->>PG: Ejecuta Server Component
    PG->>NA: getServerSession(authOptions)
    NA-->>PG: Session { user: { name, role: "requester" } }
    PG-->>U: Renderiza Dashboard ✅
```

---

## Referencia de Componentes

| Componente | Tipo | Archivo | Responsabilidad |
|---|---|---|---|
| `LoginForm` | Client | `components/auth/LoginForm.tsx` | Form de login, botones demo |
| `AuthGuard` | Client | `components/auth/AuthGuard.tsx` | Protege rutas client-side |
| `Navbar` | Client | `components/layout/Navbar.tsx` | Nav con usuario y rol |
| `ProcurementForm` | Client | `components/procurement/ProcurementForm.tsx` | Flujo en 3 pasos |
| `IntentPreview` | Server-compatible | `components/procurement/IntentPreview.tsx` | Muestra BecknIntent parseado |
| `Providers` | Client | `components/Providers.tsx` | Wraps SessionProvider |
| `parse/route.ts` | API Route | `app/api/procurement/parse/route.ts` | Proxy → IntentParser |
| `discover/route.ts` | API Route | `app/api/procurement/discover/route.ts` | Proxy → BAP |
| `auth.ts` | Config | `lib/auth.ts` | SSO stub (Credentials provider) |
| `types.ts` | Types | `lib/types.ts` | BecknIntent, ParseResult, UserRole |
| `api.ts` | Client | `lib/api.ts` | Funciones HTTP del browser |
