**STRATEGIC BRIEFING**

**Agentic AI Procurement Agent\
on Beckn Protocol**

AI-on-DPI \| Enterprise Procurement Transformation

# 2. Problem Statement & Market Context

## 2.1 The Core Problem

Enterprise procurement is stuck in a closed-platform model that hasn\'t
fundamentally changed in 20 years. Here\'s what that looks like in
practice:

Platform Lock-in and Rent Extraction. SAP Ariba and Coupa dominate
enterprise procurement with a combined market share exceeding 60% in
large enterprises (Gartner, 2025). These platforms charge subscription
fees, transaction fees, and supplier enablement fees - often totaling
2-5% of procurement spend. For a company processing \$500M in annual
procurement, that\'s \$10-25M in platform costs alone. Switching costs
are high because years of procurement data, supplier relationships, and
workflow configurations are locked inside these platforms.

Limited Supplier Access. Closed platforms curate their supplier
networks, which means enterprises only see sellers who\'ve onboarded
(and paid) to be on that specific platform. This artificially limits
competition and supplier diversity. Most enterprises on Ariba access
500-2,000 suppliers for any given category - a fraction of what\'s
actually available in the market.

Manual, Slow Procurement Cycles. Despite automation claims, procurement
still involves significant human effort. A typical purchase request goes
through 5-8 approval stages, involves 3-4 rounds of manual supplier
comparison, and takes 5-15 business days from request to order. The
procurement team at a Fortune 500 company spends roughly 65% of their
time on routine, repetitive tasks that could be automated (Deloitte CPO
Survey, 2024).

Compliance Burden. Every procurement decision needs documentation for
auditors. In practice, the reasoning behind supplier selection is often
reconstructed after the fact - not captured in real time. This makes
audit preparation time-consuming and error-prone.

## 2.2 Why Existing Solutions Fall Short

  ------------------------------------------------------------------------
  **Solution**      **What It Does**        **Where It Falls Short**
  ----------------- ----------------------- ------------------------------
  SAP Ariba / Coupa End-to-end procurement  Vendor lock-in, high fees,
                    on closed marketplace   limited supplier pool, slow
                                            innovation cycles

  GPO (Group        Aggregated buying power Limited categories, inflexible
  Purchasing)                               contracts, no real-time market
                                            discovery

  AI Copilots       Assists humans with     Still operates within closed
  (e.g., Microsoft  procurement tasks       platforms; doesn\'t transact
  Copilot for                               autonomously; no open network
  procurement)                              access

  Manual RFQ        Direct outreach to      Labor-intensive, inconsistent
  Process           suppliers               evaluation, no audit trail,
                                            15-30 day cycle times

  Beckn/ONDC        Open commerce network   Designed for
  (without AI)      for discovery and       consumer-to-business;
                    transactions            enterprise workflows
                                            (approval, compliance,
                                            negotiation) not supported
                                            natively
  ------------------------------------------------------------------------

> *[The gap isn\'t in the protocol or the AI individually - it\'s in the
> integration layer]{.mark}. Beckn provides the open network. LLMs
> provide the intelligence. What\'s missing is an enterprise-grade
> agentic system that bridges the two - handling the full procurement
> workflow autonomously while maintaining the compliance and control
> enterprises require.*

## 2.3 Market Opportunity & Timing

Three forces are converging to make this opportunity time-sensitive:

First, [DPI adoption]{.mark} is accelerating globally. India\'s ONDC has
crossed 500K+ sellers and is processing millions of transactions
monthly. Brazil, the EU, and several African nations are exploring
similar open commerce protocols. The World Bank and UNDP have endorsed
DPI as a development priority. This isn\'t a niche experiment anymore -
it\'s a global infrastructure trend.

Second, [agentic AI has reached a practical tipping point]{.mark}.
GPT-4, Claude, Gemini, and open-source models now support reliable
multi-step reasoning, tool use, and autonomous task completion.
Frameworks like LangChain, AutoGen, and CrewAI have matured to the point
where building production-grade agents is feasible - not just a research
exercise. Gartner projects that by 2028, 33% of enterprise software
applications will include agentic AI, up from less than 1% in 2024.

Third, [procurement budgets are under pressure]{.mark}. CFOs are
demanding 15-20% cost reductions across support functions (McKinsey
Global CFO Survey, 2025). Procurement platform licensing is a visible,
controllable cost line - making it an obvious target for optimization.

## 2.4 Market Sizing

The global enterprise procurement software market is valued at
approximately \$9.5 billion in 2025 (IDC). The addressable segment for
AI-on-open-network procurement is a subset: enterprises with \>\$100M in
procurement spend that operate in markets with active
Beckn/ONDC-compatible networks. We estimate this at \$1.2 billion today,
growing to \$4.2 billion by 2030 as more countries adopt interoperable
commerce standards.

For Infosys specifically, a conservative scenario targets 15-20
enterprise deployments in the first 18 months, each worth \$2-5M in
implementation and managed services revenue. That\'s a \$30-100M
pipeline from this single solution.

# 3. Proposed Solution Architecture

## 3.1 High-Level Overview

The solution is an enterprise-grade agentic AI system that acts as an
[intelligent Beckn Application Platform (BAP)]{.mark}. It sits between
enterprise users and the open commerce network, translating natural
language procurement requests into protocol-compliant transactions while
enforcing enterprise policies, approval workflows, and compliance
requirements.

The system operates in [three modes]{.mark}: [fully autonomous]{.mark}
(for routine, pre-approved procurement below configurable thresholds),
[human-in-the-loop]{.mark} (for purchases requiring approval), and
[advisory]{.mark} (providing recommendations without executing). The
[enterprise controls which mode applies to which category and spend
level.]{.mark}

![A diagram of a software AI-generated content may be
incorrect.](media/image1.png){width="6.531944444444444in"
height="3.2104166666666667in"}

## 3.2 Core Technical Components

### 3.2.1 Natural Language Intent Parser

The intent parser [converts free-form procurement requests into
structured JSON]{.mark} that maps directly to Beckn search parameters.
For example, \"I need 500 units of A4 printer paper, 80gsm, delivered to
our Bangalore office within 5 days, budget under ₹2 per sheet\" becomes
a structured intent with item descriptors, quantity, location
coordinates, delivery timeline, and budget constraints.

Implementation approach: LLM Call with structured output parsing. The
parser uses a schema-constrained decoding approach to guarantee valid
JSON output conforming to the Beckn intent schema. Fallback to a smaller
model (GPT-4o-mini) for simple, well-structured requests to reduce
latency and cost.

### 3.2.2 Beckn BAP Client

The BAP client implements the [five core]{.mark} [Beckn transaction
flows]{.mark}. The /[search]{.mark} call broadcasts the procurement
intent across the network - this is fundamentally different from
querying a single marketplace. Multiple sellers respond asynchronously
via /[on_search callbacks]{.mark}. The /[select]{.mark} flow allows the
agent to signal interest and negotiate terms. /[init]{.mark} and
/[confirm]{.mark} handle order placement, and /[status]{.mark} provides
tracking.

Key engineering challenge: Beckn responses are asynchronous and come
from diverse sellers with different catalog formats. [The catalog
normalization layer standardizes these into a unified schema for the
comparison engine.]{.mark} We handle this with a combination of schema
mapping rules and an LLM-based normalizer for edge cases.

### 3.2.3 AI Comparison & Scoring Engine

The comparison engine scores seller offers across multiple dimensions:
[price]{.mark} (weighted by volume discounts and total cost of
ownership), [delivery reliability]{.mark} (historical fulfillment rate,
estimated delivery time), [quality indicators]{.mark} (ratings,
certifications, return rates), and [compliance]{.mark} (whether the
seller meets enterprise-specific requirements like sustainability
certifications or geographic restrictions).

[Every score comes with an explanation]{.mark}. The agent doesn\'t just
rank sellers - it tells the procurement team why Seller A is recommended
over Seller B. This explainability is critical for audit compliance and
user trust. Implemented using a [ReAct]{.mark}-style reasoning loop
where the agent thinks through each criterion step by step.

### 3.2.4 Negotiation Engine

Beckn\'s /select flow supports term modification - the buyer can propose
different prices, quantities, or delivery terms. The negotiation engine
uses this capability with configurable strategies: [always counter-offer
below a threshold,]{.mark} accept [within a percentage of
budget]{.mark}, [escalate to human if]{.mark} the gap exceeds a limit.

[Strategy policies are set per procurement category by the
enterprise]{.mark}. For commodity items, aggressive automated
negotiation is appropriate. For specialized equipment, the agent shifts
to an advisory role. The engine learns from negotiation outcomes over
time, adjusting its approach based on what works with specific seller
segments.

### 3.2.5 Agent Memory & Learning

The memory module [stores past procurement patterns in a vector
database]{.mark}. When a new request comes in, the agent retrieves
similar past transactions - what was ordered, from which sellers, at
what price, and how the delivery performed. This enables recommendations
like \"Last quarter, you ordered similar items from Seller X at
₹1.8/unit with 98% on-time delivery. They\'re available on the network
now.\"

The memory also captures negotiation outcomes, seasonal price patterns,
and supplier reliability trends. [Over time, the agent becomes more
effective]{.mark} - not just for individual users, but across the
enterprise.

## 3.3 Technology Stack

  --------------------------------------------------------------------------
  **Layer**       **Technology**            **Rationale**
  --------------- ------------------------- --------------------------------
  Frontend        React 18 + Next.js 14,    Enterprise-grade UI framework
                  TypeScript, Tailwind CSS, with SSR for performance;
                  ShadCN UI                 TypeScript for type safety

  API Gateway     Kong Gateway or AWS API   Handles auth, rate limiting,
                  Gateway                   routing; Kong preferred for
                                            on-prem flexibility

  Agent Framework LangChain / LangGraph     Mature agent orchestration with
                  (Python)                  tool-use, memory, and
                                            observability; LangGraph for
                                            complex multi-step workflows

  LLM Provider    GPT-4o (primary), Claude  Multi-provider for resilience;
                  Sonnet (fallback),        model routing based on task
                  GPT-4o-mini (lightweight  complexity
                  tasks)                    

  Beckn Client    Python + aiohttp (async   Async-first for handling
                  HTTP), custom protocol    concurrent multi-seller
                  adapter                   responses

  Database        PostgreSQL 16             Proven enterprise RDBMS; Redis
                  (transactional), Redis 7  for catalog caching and session
                  (caching)                 state

  Vector DB       Qdrant (self-hosted) or   Agent memory for procurement
                  Pinecone (managed)        patterns; Qdrant preferred for
                                            data sovereignty

  Event Streaming Apache Kafka              Decoupled event-driven
                                            architecture for audit logging,
                                            real-time tracking, system
                                            integration

  Orchestration   Kubernetes (EKS/AKS/GKE), Container orchestration with
                  Helm charts, ArgoCD       GitOps deployment

  Observability   Prometheus, Grafana,      Full-stack monitoring; LangSmith
                  OpenTelemetry, LangSmith  specifically for LLM tracing and
                                            evaluation

  CI/CD           GitHub Actions, Docker,   Infrastructure as code;
                  Terraform                 automated testing and deployment
  --------------------------------------------------------------------------

## 3.4 Integration Architecture

The system integrates with the enterprise ecosystem at four key points:

-   **Identity & Access (Keycloak):** SSO integration via SAML 2.0 or
    OIDC. [Role-based]{.mark} access control maps procurement roles
    (requester, approver, admin) to system permissions. The agent
    respects these roles - a requester can\'t bypass approval
    thresholds.

-   **ERP (SAP S/4HANA / Oracle ERP Cloud):** Bidirectional sync via
    OData APIs (SAP) or REST APIs (Oracle). Purchase orders created by
    the agent are pushed to the ERP. Budget availability is checked in
    real-time before order confirmation. Goods receipt and invoice
    matching flow back to update procurement status.

-   **Compliance & Audit (Splunk / ServiceNow):** [Every agent
    decision - search parameters, seller evaluations, negotiation steps,
    approval actions - is logged as a structured event to Kafka]{.mark},
    then sunk to the enterprise\'s SIEM or audit platform. The audit
    trail includes the agent\'s reasoning at each step, not just the
    outcome.

-   **Communication (Slack / Teams / Email):** Notification webhooks for
    approval requests, order confirmations, delivery updates, and
    exception alerts. Conversational interface option - users can
    interact with the agent directly via Slack/Teams.

# 4. Detailed User Stories & Scenarios

## 4.1 Story: Routine Office Supply Procurement

**Persona:** Priya Sharma, Procurement Coordinator at a 10,000-employee
IT services company in Bangalore. Handles 200+ routine purchase requests
monthly.

**Current State (As-Is):**

Priya receives a request via email for 500 reams of A4 paper. She logs
into SAP Ariba, searches the catalog, compares 3-4 suppliers manually,
creates a purchase requisition, routes it for approval (which takes 2-3
days), then converts it to a PO. Total cycle: 5-7 days. She repeats this
process 15-20 times a day for similar routine items. She estimates that
70% of her work is repetitive data entry and waiting for approvals.

**Future State (To-Be):**

Priya types into the procurement dashboard: \"500 reams A4 paper, 80gsm,
white, delivered to Building C, Whitefield campus, within 3 business
days.\" The agent processes this in seconds.

**Step-by-step user journey:**

-   Priya submits the natural language request via the dashboard (or
    [Slack]{.mark}).

-   The agent parses the request into a structured intent: item=A4 paper
    80gsm, qty=500 reams, location=12.9716°N 77.5946°E, delivery=3 days.

-   The agent broadcasts a /search on ONDC, reaching 50+ stationery
    sellers in the Bangalore area.

-   Within 8 seconds, 12 sellers respond with offers. The agent
    normalizes all responses.

-   The comparison engine scores offers: Seller A (₹195/ream, 4.8★,
    2-day delivery, ISO 9001), Seller B (₹189/ream, 4.5★, 3-day
    delivery), etc.

-   The agent auto-negotiates with top 3 sellers via /select with a 5%
    discount counter-offer. Seller B accepts ₹180/ream.

-   Since the total (₹90,000) is below Priya\'s auto-approval threshold
    (₹1,00,000), the agent proceeds to /init and /confirm.

-   Order placed. Priya gets a Slack notification with the full
    comparison, reasoning, and order confirmation. Total time:
    [45]{.mark} seconds.

**[Technical Workflow]{.mark}:** NL Parser → Beckn /search (broadcast) →
/on_search (collect) → Catalog Normalizer → Comparison Engine (scoring +
explainability) → Negotiation Engine (/select with modified terms) →
Policy Check (threshold validation) → /init → /confirm → Kafka event
(audit + ERP sync) → Notification dispatch.

**Expected Outcome:** Procurement cycle reduced from 5-7 days to under 1
minute. Priya\'s team handles 3x the volume with the same headcount.
Annual savings of ₹12-15 lakh in platform fees plus 8-12% on item costs
through automated negotiation.

## 4.2 Story: High-Value IT Equipment with Approval Workflow

**Persona:** Rajesh Menon, IT Director at a financial services firm.
Needs to procure 200 enterprise laptops for a new office.

**Current State:**

Rajesh\'s team creates an RFQ, sends it to 5 pre-approved vendors, waits
7-10 days for responses, builds a comparison spreadsheet manually,
presents to the CFO for approval, negotiates with the selected vendor
over 3-4 calls, and places the order. End-to-end: 3-4 weeks. The
comparison spreadsheet is often incomplete and doesn\'t capture the full
reasoning.

**Future State:**

Rajesh submits: \"200 business laptops, 16GB RAM, 512GB SSD, i7 or
equivalent, Windows 11 Pro, 3-year warranty, deliver to Mumbai HQ within
15 business days, budget ₹1.6 crore.\"

-   Agent parses and creates structured intent with detailed technical
    specifications.

-   Multi-network search across ONDC and other Beckn-compatible
    networks. Agent identifies 8 sellers with matching inventory.

-   Comparison engine scores on price, warranty terms, delivery
    timeline, seller rating, and compliance (the firm requires ISO
    27001-certified suppliers for IT equipment).

-   Agent presents top 3 options to Rajesh with detailed comparison and
    reasoning. Highlights that Seller C offers the best total cost of
    ownership despite a 4% higher unit price - because of superior
    warranty terms and a bulk discount at 200+ units.

-   Rajesh reviews and selects Seller C. [Since the total (₹1.52 crore)
    exceeds Rajesh\'s approval authority, the agent routes to the
    CFO]{.mark}.

-   CFO receives a notification with the full comparison, agent
    reasoning, and one-click approve/reject. CFO approves in 10 minutes.

-   Agent executes /init and /confirm. Order placed with full audit
    trail.

-   Real-time tracking via /status. Rajesh sees delivery progress on the
    dashboard.

**Expected Outcome:** Cycle time reduced from 3-4 weeks to 2 days.
Comparison quality improves - the agent evaluates more sellers more
rigorously than a manual process. The audit trail eliminates 2 weeks of
compliance documentation effort.

## 4.3 Story: Emergency Procurement Under Time Pressure

**Persona:** Anita Desai, Facilities Manager at a hospital chain. A
critical medical supply (PPE kits) is running low due to an unexpected
surge.

**Current State:**

Anita calls 8 suppliers one by one. Half don\'t pick up. Two are out of
stock. She gets 3 quotes verbally, negotiates on the phone, places an
emergency order - but can\'t document the process properly under time
pressure. The auditors later flag the purchase as non-compliant.

**Future State:**

-   Anita types: \"URGENT: 10,000 PPE kits, Level 3 protection, deliver
    to 4 hospital locations within 24 hours.\"

-   Agent [detects urgency flag]{.mark}. Activates emergency procurement
    mode - wider search radius, parallel queries to all Beckn networks,
    relaxed price thresholds.

-   Within 15 seconds, agent identifies 6 sellers with available stock.
    Two can deliver within 24 hours.

-   Agent auto-selects the fastest supplier that meets quality
    requirements (Level 3 certification). Flags the CFO for emergency
    approval with a 60-minute auto-approve countdown.

-   CFO approves immediately. Order confirmed across 4 delivery
    locations simultaneously.

-   Full audit trail captured automatically - every decision documented
    with reasoning, even under emergency conditions.

**Expected Outcome:** Emergency procurement reduced from 4-6 hours of
frantic calls to 3 minutes of automated action. Full compliance
maintained even under pressure.

## 4.4 Story: Cross-Category Strategic Sourcing Analysis

**Persona:** Vikram Patel, Chief Procurement Officer at a manufacturing
conglomerate. Wants to benchmark current supplier contracts against
open-market alternatives.

**Current State:**

Vikram\'s team runs a quarterly sourcing analysis. It takes 3 analysts 2
weeks to compare existing contracts against market rates for their top
50 procurement categories. The analysis is always incomplete because
they can only check a handful of alternative suppliers per category.

**Future State:**

-   Vikram initiates a \"sourcing benchmark\" run from the analytics
    dashboard for all 50 categories.

-   The agent runs shadow /search queries across ONDC for each
    category - not to buy, but to collect current market pricing.

-   For each category, the agent compares current contract terms against
    live market offers, flagging categories where the enterprise is
    overpaying by more than 10%.

-   Generates a benchmarking report: 12 of 50 categories show
    significant savings potential, totaling ₹8.3 crore annually.

-   For each flagged category, the agent provides specific alternative
    suppliers with pricing, ratings, and suggested negotiation approach.

-   Vikram uses this report in contract renewal discussions - with
    data-backed negotiation leverage.

**Expected Outcome:** Quarterly sourcing analysis reduced from 2 weeks
to 4 hours. Coverage expanded from a handful of alternatives to the full
open market. ₹8-12 crore in identified savings annually.

## 4.5 Story: Government e-Marketplace Procurement

**Persona:** Dr. Meera Krishnan, District Collector responsible for
procurement across 15 government offices. Subject to strict public
procurement rules (GeM compliance, L1 bidding).

**Current State:**

Government procurement follows rigid L1 (lowest bidder) rules. Dr.
Krishnan\'s staff manually enters requirements on GeM, waits for bids,
verifies each bidder\'s credentials, and awards to the lowest compliant
bidder. The process is transparent but extremely slow (15-30 days) and
doesn\'t account for quality or delivery reliability in the selection.

**Future State:**

-   Dr. Krishnan submits requirements through the agent dashboard. The
    agent is configured for government procurement rules - L1 selection
    mandatory, but with quality floor requirements.

-   Agent searches ONDC for sellers meeting minimum quality standards
    (rating ≥ 4.0, compliance certifications present).

-   Among qualified sellers, agent auto-selects L1 (lowest price) per
    government rules.

-   Full transparency report generated: all sellers considered,
    qualification reasoning, L1 selection justification.

-   RTI-ready documentation created automatically - every decision
    traceable and explainable.

**Expected Outcome:** Government procurement cycle reduced from 15-30
days to 2-3 days while maintaining full regulatory compliance. Quality
of procurement improves through the quality floor mechanism.

# 5. Technical Implementation Roadmap

The implementation follows a four-phase approach, each building on the
previous phase\'s foundation. The total timeline is 16 weeks from
kickoff to production-ready prototype.

## Phase 1: Foundation & Protocol Integration (Weeks 1-4)

**Objective: Establish working connectivity with the Beckn/ONDC network
and build the core agent framework.**

  -----------------------------------------------------------------------------------
  **Milestone**      **Deliverable**       **Skills         **Acceptance Criteria**
                                           Required**       
  ------------------ --------------------- ---------------- -------------------------
  Beckn Sandbox      Working BAP client    Protocol         BAP sends /search and
  Setup              connected to Beckn    engineering,     receives /on_search
                     sandbox               Python, async    responses successfully
                                           HTTP             

  Core API Flows     /search, /on_search,  Beckn protocol   End-to-end search flow
                     /select implemented   spec, API design working against sandbox
                                                            with 3+ seller responses
                                                            parsed

  **[NL Intent       [LLM-based parser     [LLM             [Correctly parses 15+
  Parser]{.mark}**   converting text to    integration,     diverse procurement
                     structured            prompt           requests into valid
                     intent]{.mark}        engineering,     Beckn-compatible
                                           JSON             intent]{.mark}
                                           schema]{.mark}   

  Agent Framework    LangChain/LangGraph   Python,          Agent autonomously plans
                     agent with ReAct loop LangChain, LLM   and executes a 3-step
                                           APIs             procurement workflow

  Frontend Scaffold  React/Next.js app     React,           Running locally with SSO
                     with auth, basic      TypeScript,      stub, request submission
                     request form          Next.js          functional

  Data Models        PostgreSQL schema for Database design, Schema supports full
                     requests, offers,     SQL, migrations  procurement lifecycle
                     orders, audit events                   with audit trail
  -----------------------------------------------------------------------------------

## Phase 2: Core Intelligence & Transaction Flow (Weeks 5-8)

**Objective: Build the comparison engine, complete the Beckn transaction
lifecycle, and deliver a functional procurement workflow.**

  ----------------------------------------------------------------------------
  **Milestone**   **Deliverable**   **Skills         **Acceptance Criteria**
                                    Required**       
  --------------- ----------------- ---------------- -------------------------
  Full            /init, /confirm,  Beckn protocol,  Complete order lifecycle
  Transaction     /status           state management working against sandbox
  Flow            implemented                        

  Catalog         Standardizes      Data             Handles 5+ distinct
  Normalizer      diverse seller    engineering,     seller catalog formats
                  response formats  schema mapping   correctly

  Comparison      Multi-criteria    ML/AI, scoring   Ranks sellers correctly
  Engine          scoring with      algorithms       for 10+ test scenarios
                  explainable                        with clear explanations
                  reasoning                          

  Approval        Configurable      Workflow engine, Orders above threshold
  Workflow        threshold-based   RBAC             require and receive
                  routing                            approval before /confirm

  Comparison UI   Side-by-side      React, data      Users can view, compare,
                  offer comparison  visualization    and act on agent
                  with agent                         recommendations
                  reasoning                          

  Real-time       Order status      WebSockets,      Dashboard reflects order
  Tracking        updates via       event handling   status within 30 seconds
                  /status polling +                  of change
                  webhooks                           
  ----------------------------------------------------------------------------

## Phase 3: Advanced Intelligence & Enterprise Features (Weeks 9-12)

**Objective: Add negotiation, memory, multi-network search, and
enterprise compliance features.**

  ----------------------------------------------------------------------------
  **Milestone**   **Deliverable**   **Skills         **Acceptance Criteria**
                                    Required**       
  --------------- ----------------- ---------------- -------------------------
  Negotiation     Strategy-based    AI strategy,     Agent negotiates price
  Engine          /select with term Beckn protocol   and delivery;
                  modifications                      configurable strategies
                                                     work correctly

  Multi-Network   Concurrent        Distributed      Search spans multiple
  Search          queries to 2+     systems, async   networks; graceful
                  Beckn networks    coordination     degradation when one is
                                                     down

  Agent Memory    Vector DB storing Vector           Agent references past
                  past procurement  databases, RAG,  orders in
                  patterns          embeddings       recommendations;
                                                     similarity search works

  Audit Trail     Complete decision Event streaming, Every agent action
  System          log with          Kafka, logging   logged; audit trail
                  reasoning at                       reconstructs full
                  every step                         decision chain

  Analytics       Spend analysis,   Data             Dashboard shows 6+
  Dashboard       savings tracking, visualization,   metrics with drill-down
                  supplier metrics  Recharts/D3      capability

  ERP Integration Bidirectional     ERP APIs, OData, POs created in agent
                  sync with         middleware       appear in ERP; budget
                  SAP/Oracle                         checks validated against
                                                     ERP
  ----------------------------------------------------------------------------

## Phase 4: Hardening, Testing & Production Readiness (Weeks 13-16)

**Objective: Production-grade reliability, security hardening,
performance optimization, and deployment automation.**

  -------------------------------------------------------------------------------
  **Milestone**      **Deliverable**   **Skills         **Acceptance Criteria**
                                       Required**       
  ------------------ ----------------- ---------------- -------------------------
  Performance        Agent response    Performance      P95 latency under 5s;
  Optimization       time \< 5 seconds tuning, caching  caching reduces redundant
                     for standard                       network calls by 50%+
                     requests                           

  Security Hardening Pen test          AppSec,          OWASP Top 10 addressed;
                     remediation, data encryption, RBAC data encrypted at rest
                     encryption,                        and in transit
                     access controls                    

  Integration        End-to-end test   Test automation, 80%+ code coverage; all
  Testing            suite covering    CI/CD            critical paths tested
                     all Beckn flows                    

  Evaluation Suite   20+ procurement   AI evaluation,   Agent achieves 85%+
                     scenarios with    benchmarking     accuracy on evaluation
                     ground-truth                       suite
                     scoring                            

  Containerization   Docker images,    DevOps, K8s, IaC Full stack runs via
                     Helm charts,                       docker-compose locally;
                     Kubernetes                         Helm deploys to K8s
                     manifests                          cluster

  Documentation &    Architecture      Technical        Documentation sufficient
  Demo               docs, API docs,   writing,         for handoff; demo covers
                     5-min demo video  presentation     all key capabilities
  -------------------------------------------------------------------------------

# 6. Data & AI Model Requirements

## 6.1 Data Sources & Pipeline Architecture

The system ingests data from four primary sources, each with distinct
characteristics and processing requirements:

  ---------------------------------------------------------------------------------------
  **Data Source** **Type**          **Volume**         **Freshness**   **Processing**
  --------------- ----------------- ------------------ --------------- ------------------
  Beckn/ONDC      Semi-structured   100-10,000         Real-time       Normalize → Score
  Catalog         JSON (async       responses/search                   → Cache (Redis,
  Responses       callbacks)                                           15-min TTL)

  Enterprise      Structured (ERP   50K-500K records   Daily batch     ETL → PostgreSQL →
  Procurement     exports, DB                          sync            Embed → Vector DB
  History         records)                                             (Qdrant)

  User            Semi-structured   1K-10K events/day  Real-time       Kafka → PostgreSQL
  Interaction     (request text,                       streaming       (audit) + Vector
  Logs            selections,                                          DB (learning)
                  feedback)                                            

  Supplier        Structured        Aggregated from    Weekly          Batch process →
  Performance     (ratings,         ONDC + internal    aggregation     Supplier scoring
  Data            delivery metrics,                                    model update
                  certifications)                                      
  ---------------------------------------------------------------------------------------

Data pipeline: Kafka serves as the central event bus. All data flows -
Beckn responses, user interactions, agent decisions - are published as
events. Consumers process these events for different purposes:
PostgreSQL for transactional storage, the vector database for agent
memory, the analytics engine for dashboards, and the audit log for
compliance.

## 6.2 AI/ML Models

The system uses four distinct AI capabilities, each with different model
requirements:

### 6.2.1 Intent Parsing Model

Purpose: Convert natural language procurement requests into structured
JSON conforming to the Beckn intent schema.

-   Model: GPT-4o with structured output (JSON mode) as primary; Claude
    Sonnet 4.6 as fallback.

-   Training approach: Few-shot prompting with 50+ curated procurement
    examples covering diverse categories, formats, and edge cases. No
    fine-tuning needed initially - structured output + well-designed
    prompts achieve 95%+ accuracy.

-   Evaluation: Test against 100 procurement requests spanning 15
    categories. Success = valid JSON output matching expected schema
    with all extracted fields correct.

### 6.2.2 Comparison & Scoring Model

Purpose: Score and rank seller offers across multiple dimensions with
explainable reasoning.

-   Model: LLM-based ReAct agent (GPT-4o) for reasoning; lightweight
    scoring functions (Python) for numerical comparisons.

-   Training approach: Scoring weights calibrated from historical
    procurement data. The LLM provides reasoning and handles qualitative
    factors; numerical scoring is deterministic.

-   Key design choice: Hybrid approach - deterministic scoring for
    quantifiable metrics (price, delivery time) combined with LLM
    reasoning for qualitative assessment (compliance fit, supplier
    reliability interpretation).

### 6.2.3 Negotiation Strategy Model

Purpose: Determine optimal counter-offer terms based on category,
budget, historical outcomes, and seller behavior.

-   Model: Rule-based engine (configurable per category) augmented with
    LLM for strategy selection in ambiguous cases.

-   Training approach: Initial rules set by procurement domain experts.
    Over time, reinforcement learning from negotiation outcomes refines
    strategies. The RL component is Phase 2 - Phase 1 uses
    expert-defined rules.

-   Safety guardrails: Maximum discount request capped at 20%. Agent
    cannot agree to terms outside pre-defined boundaries. All
    negotiation actions require policy compliance check before
    execution.

### 6.2.4 Memory & Retrieval Model

Purpose: Retrieve relevant past procurement patterns to inform current
decisions.

-   Model: Embedding model (OpenAI text-embedding-3-large or open-source
    e5-large-v2) for encoding procurement records; cosine similarity for
    retrieval.

-   Training approach: No custom training. Pre-trained embeddings work
    well for procurement text. Custom metadata filtering (category, date
    range, supplier) narrows retrieval.

-   Vector DB: Qdrant (self-hosted for data sovereignty) with HNSW
    indexing. Expected corpus: 50K-500K procurement records. Retrieval
    latency target: \< 100ms.

## 6.3 Model Governance & Monitoring

-   **Model Registry:** All LLM configurations (model version, prompt
    templates, temperature settings) tracked in a version-controlled
    registry. Every agent response is traceable to a specific model
    version + prompt version.

-   **Evaluation Pipeline:** Weekly automated evaluation against a
    curated test suite of 100 procurement scenarios. Metrics tracked:
    intent parsing accuracy, comparison quality (vs. human expert
    ranking), negotiation outcome (savings achieved vs. baseline),
    response latency.

-   **Drift Detection:** Monitor for model performance degradation - if
    accuracy drops below 85% on the evaluation suite or if user override
    rate exceeds 30%, trigger review and prompt adjustment.

-   **Human Override Tracking:** Every time a user overrides the
    agent\'s recommendation, the override reason is captured. Aggregated
    override data feeds back into prompt improvement and scoring
    calibration.

-   **LLM Observability:** LangSmith integration for tracing every LLM
    call - input, output, latency, token usage, cost. Enables debugging,
    cost optimization, and quality monitoring.

## 6.4 Privacy, Security & Compliance

Data handling follows a defense-in-depth approach across five
dimensions:

  --------------------------------------------------------------------------
  **Dimension**   **Requirement**       **Implementation**
  --------------- --------------------- ------------------------------------
  Data Residency  Procurement data must Self-hosted vector DB (Qdrant);
                  stay within the       PostgreSQL on enterprise cloud (AWS
                  enterprise\'s         Mumbai / Azure India); LLM calls via
                  jurisdiction          enterprise API agreements with data
                                        processing addendums

  PII Protection  No personal data in   PII scrubbing pipeline before LLM
                  LLM prompts unless    calls; procurement data is
                  strictly necessary    entity-level (company, not
                                        individual) by default

  Encryption      At rest and in        TLS 1.3 for all API calls; AES-256
                  transit               for database encryption; KMS-managed
                                        keys

  Access Control  Role-based, least     RBAC via Okta/Azure AD integration;
                  privilege             API-level authorization; audit
                                        logging of all access

  Compliance      SOX (financial        Automated audit trail satisfies SOX
  Frameworks      controls), GDPR (if   Section 404; GDPR-compliant data
                  EU suppliers), IT Act processing agreements with LLM
                  2000 (India)          providers; data retention policies
                                        configurable per regulation
  --------------------------------------------------------------------------

# 8. Success Metrics & KPIs

## 8.1 Technical Performance Metrics

  -----------------------------------------------------------------------
  **Metric**                **Target**        **Measurement Method**
  ------------------------- ----------------- ---------------------------
  Agent response time       \< 5 seconds      OpenTelemetry distributed
  (intent to                (P95)             tracing
  recommendation)                             

  Intent parsing accuracy   ≥ 95%             Weekly evaluation against
                                              100-scenario test suite

  Comparison quality (vs.   ≥ 85% agreement   Blind comparison test:
  human expert ranking)                       agent vs. expert rankings
                                              for same offers

  Beckn API success rate    ≥ 99.5%           Prometheus monitoring of
                                              API call outcomes

  System uptime             ≥ 99.9%           Kubernetes health checks +
                                              Grafana alerts

  Catalog normalization     ≥ 95%             Automated validation
  success rate                                against expected schema
  -----------------------------------------------------------------------

## 8.2 Business Impact Metrics

  -----------------------------------------------------------------------
  **Metric**                **Target**        **Measurement Method**
  ------------------------- ----------------- ---------------------------
  Procurement cycle time    70-90% reduction  Before/after comparison per
  reduction                 vs. baseline      procurement category

  Cost savings from         8-15% avg.        Compare agent-negotiated
  negotiation               reduction         prices vs. list prices over
                                              90-day rolling window

  Platform licensing cost   80-90% reduction  Direct comparison: current
  savings                                     Ariba/Coupa fees vs. open
                                              network operating costs

  Procurement team          3x throughput     Requests processed per FTE
  productivity              increase          per month, before/after

  Audit preparation time    90% reduction     Hours spent on audit prep,
                                              before/after
  -----------------------------------------------------------------------

## 8.3 User Adoption Metrics

  -----------------------------------------------------------------------
  **Metric**                **Target (6 months)** **Target (12 months)**
  ------------------------- --------------------- -----------------------
  Active users (monthly)    50+ across 3          500+ across 15
                            enterprise pilots     enterprises

  Requests processed via    1,000/month           10,000/month
  agent                                           

  Agent recommendation      ≥ 60%                 ≥ 75%
  acceptance rate                                 

  User override rate        \< 40%                \< 25%

  User satisfaction (NPS)   ≥ 30                  ≥ 50
  -----------------------------------------------------------------------

# 9. References & Supporting Research

## 9.1 Protocol & Technical Documentation

-   Beckn Protocol Specification - Core protocol spec, API definitions,
    message schemas. Start with the /api/ directory for implementation
    reference.

-   Beckn Sandbox - Test environment for BAP development. Essential for
    Phase 1 integration testing.

-   ONDC Protocol Specs - - Production implementation of Beckn for
    India\'s digital commerce network. Reference for real-world protocol
    usage patterns.

## 9.2 Industry Reports & Research

-   Gartner (2025), \"Market Share: Procurement Software, Worldwide\" -
    Market sizing and competitive landscape for enterprise procurement
    platforms.

-   Deloitte (2024), \"Global Chief Procurement Officer Survey\" -
    Insights on procurement automation priorities; finding that 65% of
    procurement time is spent on routine tasks.

-   McKinsey (2025), \"Global CFO Survey: Cost Optimization
    Priorities\" - CFOs targeting 15-20% cost reduction across support
    functions.

-   IDC (2025), \"Worldwide Procurement Applications Market Forecast\" -
    \$9.5B global market size and growth projections.

-   Gartner (2024), \"Predicts 2025: AI Agents Will Transform Enterprise
    Software\" - Projection that 33% of enterprise software will include
    agentic AI by 2028.

-   World Bank (2024), \"Digital Public Infrastructure: A Foundation for
    Digital Transformation\" - Framework for DPI adoption and impact
    assessment.

-   UNDP (2024), \"DPI: An Approach to Digitalization\" - Policy
    guidance on DPI implementation for developing economies.

## 9.3 DPI Frameworks & Standards

-   DPGA (Digital Public Goods Alliance) - digitalpublicgoods.net -
    Registry and standards for digital public goods, including Beckn
    Protocol.

-   India\'s DPIIT Guidelines on ONDC - commerce.gov.in - Regulatory
    framework for open network digital commerce in India.

-   Beckn Foundation - becknfoundation.org - Governance body for the
    Beckn protocol; publishes protocol evolution roadmap.

-   EU Digital Markets Act (DMA) - Regulatory context for
    open/interoperable digital platforms in Europe.

-   G20 Digital Public Infrastructure Framework (2023) - International
    consensus document on DPI principles and implementation guidance.

## 9.4 Related Case Studies

-   ONDC Pilot Results (2024-2025) - ONDC\'s published metrics showing
    500K+ sellers, 12M+ monthly transactions, and growing enterprise
    adoption in India.

-   Singapore\'s SGTS (Singapore Government Tech Stack) - Reference
    architecture for government adoption of open digital infrastructure
    with AI integration.

-   Brazil\'s Pix Payment DPI - Case study in rapid DPI adoption and the
    emerging AI-on-DPI ecosystem built on top of instant payments
    infrastructure.

-   Estonia\'s X-Road - Long-running DPI example demonstrating how open
    infrastructure enables ecosystem innovation over decades.

    **Our Summary**

    **Understanding of the project**

    The project proposes creating an autonomous AI agent (agentic AI) to
    transform the way companies handle procurement, leveraging open
    digital commerce networks based on the Beckn protocol (such as ONDC
    in India).

    Instead of relying on closed platforms like SAP Ariba or Coupa, the
    system acts as an intelligent agent that purchases directly from an
    open marketplace---rapidly, automatically, and transparently---while
    adhering to corporate and compliance regulations.

    **What we\'re building**

    It is proposed to build an AI agent system that acts as a "Smart
    Buying Platform" (BAP) atop Beckn, featuring the following
    characteristics:

-   Receives requests in natural language ("I need 500 reams of
    paper...").

-   Searches for suppliers within an open network, rather than a closed
    marketplace.

-   Automatically compares, negotiates, and selects offers.

-   Executes purchases or requests approval in accordance with corporate
    policies.

-   Maintains a complete audit trail of all decisions.

    The agent will be able to operate in three modes:

-   Autonomous: Routine purchases within approved thresholds.

-   Human-in-the-loop: Requires approval (CFO, manager, etc.).

-   Advisor: Recommends, but does not execute.

    **How it\'s structured**

    **Key milestones.**

    Reduction in purchasing cycles and lead times

    Processes that previously took days or weeks now take minutes

    Price savings through negotiation

    Cost reductions on closed platforms

    Comparison quality improves - the agent evaluates more sellers more
    rigorously than a manual process

    The audit trail eliminates 2 weeks of compliance documentation
    effort.

    Decisiones explicables

    Trazabilidad correcta

    ![](media/image2.png){width="6.531944444444444in"
    height="7.874305555555556in"}

    ![](media/image3.png){width="6.531944444444444in"
    height="9.090277777777779in"}
