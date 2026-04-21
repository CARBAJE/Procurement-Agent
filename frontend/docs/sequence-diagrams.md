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
    PF->>NX: POST /api/procurement/discover { beckn_intent }
    NX->>BAP: POST /discover { BecknIntent }
    BAP->>ONIX: POST /bap/caller/discover
    ONIX-->>BAP: ACK
    ONIX->>BAP: POST /bap/receiver/on_discover (callback)
    BAP-->>NX: { transaction_id, offerings, status }
    NX-->>PF: Offerings
    PF-->>U: Muestra proveedores encontrados
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
        PR->>IP: axios.POST http://127.0.0.1:8001/parse<br/>{ query }
        IP->>IP: Clasifica complejidad<br/>(len > 120 o ≥ 2 números → qwen3:8b)
        IP->>OL: Prompt con query
        OL-->>IP: JSON estructurado
        IP-->>PR: ParseResult {<br/>  intent: "PurchaseOrder",<br/>  confidence: 0.8,<br/>  beckn_intent: { item, quantity,<br/>    delivery_timeline, ... },<br/>  routed_to: "qwen3:1.7b"<br/>}
        PR-->>API: ParseResult
        API-->>PF: ParseResult
        PF->>PF: setParseResult(result)<br/>setStep("preview")
        PF->>IV: Renderiza IntentPreview
        IV-->>U: Muestra intent interpretado<br/>con % confianza
    else IntentParser no disponible
        PR-->>API: Mock { item: query, confidence: 0.95 }
        API-->>PF: Mock ParseResult
        PF-->>U: Muestra preview con datos mock
    end
```

---

## 4. Discovery — Con ONIX (Red Beckn Real)

Flujo completo cuando el Docker stack está corriendo. Usa callbacks async de Beckn v2.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant PF as ProcurementForm.tsx
    participant DR as discover/route.ts<br/>(Next.js API)
    participant BAP as BAP server.py<br/>(:8000)
    participant BC as BecknClient
    participant CC as CallbackCollector
    participant ONIX as ONIX Adapter<br/>(Go :8081)
    participant BPP as /bpp/discover<br/>(server.py local)

    U->>PF: Click "Confirmar y buscar"
    PF->>PF: handleConfirm()<br/>Toma beckn_intent del parseResult
    PF->>DR: fetch /api/procurement/discover<br/>{ BecknIntent }

    DR->>DR: getServerSession() — verifica auth
    DR->>BAP: axios.POST http://127.0.0.1:8000/discover<br/>{ BecknIntent }

    BAP->>BAP: discover()<br/>Construye BecknIntent desde body
    BAP->>BC: discover_async(intent, collector)
    BC->>CC: collector.register(txn_id, "on_discover")
    BC->>ONIX: POST /bap/caller/discover<br/>{ context, message.intent }
    ONIX-->>BC: ACK { status: "ACK" }

    ONIX->>BPP: POST /bpp/discover<br/>(ruteo local)
    BPP->>BPP: asyncio.create_task(<br/>_send_local_on_discover)
    BPP-->>ONIX: ACK

    Note over BPP: 100ms delay (async)

    BPP->>BAP: POST /bap/receiver/on_discover<br/>{ catalogs: [_LOCAL_CATALOG] }
    BAP->>CC: collector.handle_callback("on_discover", payload)
    CC->>BC: Queue recibe callback
    BC->>BC: collector.collect() despierta<br/>_parse_on_discover()
    BC-->>BAP: DiscoverResponse { offerings: [...] }
    BAP-->>DR: { transaction_id, offerings, status: "live" }
    DR-->>PF: Offerings
    PF->>PF: setDiscoverResult(data)<br/>setStep("submitted")
    PF-->>U: Muestra 3 proveedores con<br/>precio, rating, proveedor
```

---

## 5. Discovery — Sin ONIX (Fallback a Catálogo Local)

Cuando ONIX no está corriendo. El BAP captura el timeout y responde con el catálogo hardcodeado.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant PF as ProcurementForm.tsx
    participant DR as discover/route.ts
    participant BAP as BAP server.py
    participant BC as BecknClient
    participant ONIX as ONIX Adapter<br/>(no disponible)

    U->>PF: Click "Confirmar y buscar"
    PF->>DR: fetch /api/procurement/discover<br/>{ BecknIntent }
    DR->>BAP: axios.POST /discover

    BAP->>BC: discover_async(intent, collector, timeout=10s)
    BC->>ONIX: POST /bap/caller/discover
    ONIX--xBC: ECONNREFUSED (no corre)

    Note over BC,BAP: asyncio.wait_for expira (12s)

    BC-->>BAP: Exception (timeout / connection error)
    BAP->>BAP: except → logger.warning(...)<br/>_local_catalog_as_offerings()
    BAP-->>DR: {<br/>  transaction_id: uuid4(),<br/>  offerings: [OfficeWorld, PaperDirect,<br/>              Stationery Hub],<br/>  status: "mock"<br/>}
    DR-->>PF: Offerings (mock)
    PF-->>U: Muestra proveedores<br/>Badge "Catálogo local"
```

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
