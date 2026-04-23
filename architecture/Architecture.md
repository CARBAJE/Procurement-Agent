# Architecture - Procurement Agent

## Descripción General

El sistema es un agente de procurement que permite a usuarios interactuar mediante plataformas de mensajería (Slack o Microsoft Teams), conectándose a proveedores a través del protocolo ONDC. Toda la infraestructura corre sobre AWS Cloud.

---

## Flujo Principal

### 1. Entrada del Usuario
El usuario interactúa con el sistema a través de:
- **Slack**
- **Microsoft Teams**

Ambas plataformas se conectan vía **API Gateway**, y el acceso está protegido por un mecanismo de **Auth & Token**.

---

### 2. AWS Step Functions Workflow

Una vez autenticada la solicitud, se desencadena un flujo orquestado por **AWS Step Functions**, compuesto por las siguientes Lambdas en secuencia:

1. **Intention Parser** — Interpreta la intención del usuario a partir del mensaje recibido.
2. **Beckn BAP Client** — Se comunica con la red ONDC para buscar proveedores y productos disponibles.
3. **Comparative and Scoring** — Compara y puntúa las ofertas recibidas de los proveedores.
4. **Negotiation Engine** — Ejecuta la lógica de negociación con los proveedores seleccionados.
5. **Approval Engine** — Gestiona el proceso de aprobación final antes de confirmar la compra.

---

### 3. Agent Stack

Dentro del flujo, existe un **Agent Stack** compuesto por agentes de IA especializados que apoyan el procesamiento:

- **Parser Agent** — Parsea y estructura la información recibida.
- **Normalizer Agent** — Normaliza los datos provenientes de distintas fuentes.
- **Negotiator Agent** — Ejecuta estrategias de negociación de forma autónoma.

#### Modelos Fundacionales utilizados:
- **Chat GPT-4o**
- **Claude Sonnet 4.6**
Sin embargo, como es etapa de desarrollo, el modelo local utilizado actualmente es:
- **Ollama qwen3:1.7b**

#### Memoria del Agente:
- **ElastiCache (Valkey)** — Memoria histórica de conversaciones y transacciones.
- **OpenSearch** — Memoria semántica para búsqueda contextual.

---

### 4. Data Normalizer

Un Lambda de **Data Normalizer** actúa como puente entre el Agent Stack y el Corporate Data Center, normalizando los datos antes de persistirlos.

---

### 5. Corporate Data Center

Almacena y distribuye los datos del negocio mediante:
- **PostgreSQL** — Base de datos relacional para datos estructurados.
- **Apache Kafka** — Broker de mensajería para procesamiento de eventos en tiempo real.

---

### 6. Frontend

- **React Frontend (AWS Amplify)** — Interfaz web del sistema, desplegada con AWS Amplify, conectada al API Gateway y al Step Functions workflow.

---

### 7. Integración con ONDC

El **Beckn BAP Client** se comunica directamente con la red **ONDC** (Open Network for Digital Commerce) para descubrir proveedores, consultar catálogos y ejecutar transacciones bajo el protocolo Beckn.

---

## Resumen de Componentes

| Componente            | Tecnología                     | Rol                       |
| --------------------- | ------------------------------ | ------------------------- |
| Mensajería            | Slack / MS Teams               | Entrada del usuario       |
| API Gateway           | AWS API Gateway                | Punto de entrada HTTP     |
| Autenticación         | Auth & Token                   | Control de acceso         |
| Orquestación          | AWS Step Functions             | Coordinación del flujo    |
| Funciones             | AWS Lambda (x5)                | Lógica de negocio         |
| Agentes IA            | Parser, Normalizer, Negotiator | Procesamiento inteligente |
| LLMs                  | GPT-4o, Claude Sonnet 4.6      | Modelos fundacionales     |
| Memoria histórica     | ElastiCache (Valkey)           | Contexto de conversación  |
| Memoria semántica     | OpenSearch                     | Búsqueda por significado  |
| Base de datos         | PostgreSQL                     | Persistencia relacional   |
| Mensajería de eventos | Apache Kafka                   | Streaming de datos        |
| Frontend              | React + AWS Amplify            | Interfaz web              |
| Red de proveedores    | ONDC (Beckn)                   | Marketplace digital       |
