# Speech — Slides 1–8 (English)

---

## Slide 01 — Cover

Good moorning. My name is Eduardo, and together with my teammates José and Cristian, we developed the project called Agentic AI Procurement Agent on Beckn Protocol.


---

## Slide 02 — The Problem

To understand why that matters, we need to talk about the current state of enterprise procurement.

Today, when a buyer needs something, the process typically looks like this: on day zero, they submit a request. By day five, someone creates an RFQ — a formal request for quotation — and sends it out to available suppliers. Quotes come back a few days later. Then come the approvals, which depend on calendars and authorization chains. By day thirty, if everything went smoothly, the purchase order finally reaches the supplier.

Thirty days. For a procurement order.

---

## Slide 03 — Current Reality

On top of slow cycles, there's another problem: the platforms that dominate enterprise procurement today — SAP Ariba and Coupa — come with very high costs: subscription fees, transaction fees, and supplier enablement fees just to get a vendor onto the platform.

And beyond the cost, there's a deeper issue: these are closed platforms. They control which suppliers can participate, so companies only see the vendors who have paid to be listed there. If a faster or cheaper supplier isn't registered on that platform, it simply doesn't exist for the buyer.

---

## Slide 04 — Our Solution

Our solution is an AI agent that converts natural language text into a confirmed purchase order including a negotiation — a PO.

The agent discovers suppliers in real time, compares offers, automatically negotiates to bring the price down, and closes the purchase with a complete audit trail. The result is a procurement process that goes from days to seconds.

---

## Slide 05 — How It Works

How does it work? There are five steps.

**First, understand.** The buyer types what they need in plain language. Internally, the system processes the text, classifies the intent, and extracts a structured object with the item type, quantity, budget, and delivery location.

**Second, discover.** The system sends a request through the Beckn protocol, using the ONIX adapter, which signs the request and distributes it to connected supplier networks. Responses arrive asynchronously, without blocking the system.

**Third, evaluate.** With the offers received, the RankNet ML model ranks them by comparing price, delivery speed, and supplier risk. It also checks past orders to give an advantage to suppliers with a good track record.

**Fourth, negotiate.** The agent sends automatic counter-offers to bring the price down, within the policy limits defined by the company.

**Fifth, confirm.** The order is closed through the full Beckn handshake and everything is recorded in the ERP.

---

## Slide 06 — Enterprise Capabilities

Here are some of the key features of the agent.

It uses **local AI**, which means procurement data never leaves the company's own servers. But it's scalable — it can connect to external models like Claude if more capacity is needed.

It uses **Beckn Protocol v2**, which cryptographically signs every transaction and allows connecting to any supplier on the open network, with no prior bilateral agreements.

It has **autonomous negotiation**, which automatically reduces purchase prices within the allowed margins.

It uses **ML Scoring with RankNet** to rank suppliers, and **pgvector** to search past orders and factor them into new ones — the system learns from the company's purchase history.

And it has an **Audit Trail that complies with SOX 404** — that's a financial compliance standard that requires being able to demonstrate and reconstruct every decision made in the process. In our case, every event is recorded with the system's complete reasoning, not just the final outcome.

---

## Slide 07 — Business Impact

With this system, what we aim to achieve is the following.

First, reduce the **procurement cycle** from days to seconds on autonomous orders — by eliminating the manual steps that make the process slow today.

Second, generate **savings of five to ten percent per order** through automatic negotiation, recovering money that is currently left on the table simply because no one has time to negotiate every quote.

Third, open up the **supplier pool** — instead of a fixed list of pre-integrated vendors, any supplier connected to Beckn would be available from day one.

And fourth, make **regulatory compliance** stop being extra work — the audit trail would exist automatically as part of the process, with no additional projects required.

---

## Slide 08 — Differentiators

This table summarizes why this is different from what exists today.

Traditional platforms like SAP or Coupa are closed systems: their supplier catalog is fixed, they have no LLM integration, workflows are manual, and they don't learn across purchases.

We do the opposite on two key points.

First, **open protocol with no bilateral agreements**. Any supplier that speaks Beckn is available from day one, with no prior integration and no onboarding fee. Traditional platforms can't offer this because their business model depends precisely on those charges.

Second, **governed autonomy**. This is not a chatbot that places orders. It's a system where the agent has real authority to negotiate and close purchases, but is bounded by three independent governance layers — model-level rules, service-level rules, and Beckn contract schema validation — so it can never exceed company policy.

That concludes my part. I'll hand it over to [name] to continue with the architecture and the system's design decisions.
