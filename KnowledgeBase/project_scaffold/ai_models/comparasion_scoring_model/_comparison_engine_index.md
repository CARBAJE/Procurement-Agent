---
title: "Comparison & Scoring Engine — Master Index"
tags: [comparison-engine, ml-roadmap, moc, executive-summary, index]
type: MOC
related:
  - "[[comparison_scoring_engine]]"
  - "[[comparison_scoring_model]]"
  - "[[nl_intent_parser]]"
  - "[[beckn_bap_client]]"
  - "[[agent_memory_learning]]"
  - "[[model_governance_monitoring]]"
  - "[[business_impact_metrics]]"
  - "[[technical_performance_metrics]]"
  - "[[microservices_architecture]]"
---

# Comparison & Scoring Engine: Architectural Roadmap & ML Evolution

> **Map of Content (MOC).** This file is the root node of the Comparison Engine knowledge cluster. Navigate to each phase via the links below. For the live service implementation, see [[comparison_scoring_engine]].

| Field            | Value                                                                                          |
|------------------|-----------------------------------------------------------------------------------------------|
| **Status**       | Principal Architect Review — Strategic Roadmap                                                 |
| **Date**         | 2026-05-05                                                                                     |
| **Owner**        | Principal AI Architect / Lead ML Researcher                                                    |
| **Live Service** | `services/comparative-scoring` (Lambda 3, `:8003`) — see [[comparison_scoring_engine]]        |
| **Supersedes**   | `docs/architecture/comparison_engine_roadmap.md` (executive-only overview)                    |

---

## Executive Summary

The [[comparison_scoring_engine]] occupies the terminal decision position in the Beckn BAP procurement pipeline: it ingests a heterogeneous set of `DiscoverOffering` records — produced by one or more `on_search` callbacks distributed across the Beckn federated network — and collapses them into a ranked recommendation with a defensible justification for the Infosys buyer.

The architectural challenge is that procurement preference is **not a stationary function**. The relative importance of price, delivery speed, supplier certification, and ESG compliance varies by procurement category, budget cycle, cost-centre policy, and individual buyer authority level. Encoding this preference as a fixed weight vector — the approach inherited from Phase 1 — produces a model that is easy to audit but impossible to improve without manual intervention.

This document traces the engine's intended evolution along a single axis: **how much of the decision logic is learned from data rather than prescribed by domain experts**.

The three phases correspond to three distinct points on the **bias-variance-computability Pareto frontier**:

| Phase | Inductive Bias | Learning Signal | Objective |
|---|---|---|---|
| [[phase1_hybrid_react\|1 — Hybrid ReAct]] | Maximum (hand-coded formulae) | None | Heuristic quality |
| [[phase2_learning_to_rank\|2 — LTR via SGD]] | Moderate (parameterised linear/MLP) | Pairwise ranking loss | Statistical accuracy |
| [[phase3_optnet_e2e\|3 — OptNet (E2E)]] | Minimum (solver-embedded structure) | Financial regret | Decision quality |

The central thesis of [[phase3_optnet_e2e]] — which motivates the full roadmap — is that **optimising for predictive accuracy (MSE, ranking loss) is not the same as optimising for the financial consequence of being wrong**. A ranking model that misorders two suppliers whose realised costs differ by ₹500 incurs the same loss as one that misorders two whose costs differ by ₹5,00,000. End-to-end differentiable optimisation (OptNet, cvxpylayers, SPO+) corrects this misalignment by propagating gradients directly from the realised procurement outcome back through the mathematical solver and into the neural encoder.

The phases progress along a structural axis:

```
Phase 1                      Phase 2                           Phase 3
─────────────────────────────────────────────────────────────────────────
Hybrid Rules + LLM ReAct  →  Learning to Rank (SGD)  →  E2E Differentiable
                                                          Optimization (OptNet)
─────────────────────────────────────────────────────────────────────────
Static weights               Learned weights               Learned representations
Human-coded math             Human-coded math              Solver-aware gradients
Explainable                  Self-calibrating              Decision-aware
LLM-bound latency (7–12 s)   Millisecond inference         50–500 ms (LP + encoder)
```

---

## Notation Reference

| Symbol | Type | Semantics |
|---|---|---|
| $n$ | $\mathbb{Z}_{>0}$ | Number of candidate supplier offerings in a session |
| $d$ | $\mathbb{Z}_{>0}$ | Feature dimensionality |
| $\mathbf{x}_i \in \mathbb{R}^d$ | Vector | Feature vector for offering $i$ |
| $\mathbf{X} \in \mathbb{R}^{n \times d}$ | Matrix | Full feature matrix for a session |
| $s_i \in \mathbb{R}$ | Scalar | Predicted score for offering $i$ |
| $\theta$ | Parameter set | Learnable parameters of the scoring function |
| $\mathbf{w} \in \mathbb{R}^d$ | Vector | Linear weight vector (Phase 2) |
| $\mathbf{z} \in [0,1]^n$ | Vector | LP-relaxed allocation / selection vector (Phase 3) |
| $\mathbf{c}_\theta \in \mathbb{R}^n$ | Vector | Neural predicted cost vector $f_\theta(\mathbf{X})$ |
| $\mathbf{c}^{\text{true}} \in \mathbb{R}^n$ | Vector | Post-realisation ground-truth cost vector |
| $\mathbf{z}^* \in [0,1]^n$ | Vector | Optimal selection given $\mathbf{c}_\theta$ via LP solver |
| $\mathbf{z}^{\text{true}} \in \{0,1\}^n$ | Vector | Buyer's realised procurement decision |
| $S_{ij} \in \{-1,0,+1\}$ | Scalar | Pairwise preference label ($+1$: $i$ preferred over $j$) |
| $\lambda_{ij}$ | Scalar | RankNet gradient signal for pair $(i,j)$ |
| $B$ | Scalar | Procurement budget cap (INR) |
| $\tau_i$ | Scalar | Delivery slack: $D_{\text{deadline}} - D_{\text{promised},i}$ (hours) |
| $\delta_i(q)$ | Function | Volume discount rate at quantity $q$ for supplier $i$ |

---

## Phase Navigation

### [[phase1_hybrid_react]] — The Hybrid ReAct Pipeline (Current State)

**Status: Production.**

Deterministic quantitative math (NumPy/Pandas TCO, volume discounts, delivery feasibility) combined with a [[llm_providers|GPT-4o]]-backed [[agent_react_framework|ReAct]] qualitative reasoning loop implemented in [[agent_framework_langchain_langgraph|LangGraph]]. Fixed weight aggregator $S_i = 0.40 \cdot x_{\text{tco}} + 0.25 \cdot x_{\tau} + 0.20 \cdot x_{\text{quality}} + 0.15 \cdot x_{\text{risk}}$.

→ **Read:** [[phase1_hybrid_react]] for TCO formula, LangGraph topology, Qdrant ANN retrieval, and latency analysis.

---

### [[phase2_learning_to_rank]] — Learning to Rank via SGD

**Status: 1–2 quarter build.**

Replaces the fixed aggregator with a learnable scoring function $s_i = f_\theta(\mathbf{x}_i)$ trained on buyer override events via RankNet pairwise cross-entropy loss and LambdaRank NDCG-weighted gradients. Override events flow from the [[audit_trail_system]] → [[event_streaming_kafka|Kafka]] → nightly PyTorch training loop → [[model_governance_monitoring|MLflow]] model registry.

→ **Read:** [[phase2_learning_to_rank]] for the full RankNet closed-form, LambdaRank derivation, SGD training loop, and Kafka pipeline.

---

### [[phase3_optnet_e2e]] — End-to-End Differentiable Optimization

**Status: Research track → shadow mode → A/B.**

Embeds an LP/MILP solver as a differentiable layer (cvxpylayers / SPO+) inside the neural network, trained end-to-end against financial regret via implicit differentiation of the KKT conditions. Gradients flow through the $K_{\text{sym}}$ block matrix back into the [[embedding_models|sentence-transformer]] encoder.

→ **Read:** [[phase3_optnet_e2e]] for MILP formulation, KKT Jacobian system, SPO+ loss derivation, and the full neural architecture.

---

## Comparative Analysis

| Dimension | [[phase1_hybrid_react\|Phase 1 — Hybrid ReAct]] | [[phase2_learning_to_rank\|Phase 2 — LTR / SGD]] | [[phase3_optnet_e2e\|Phase 3 — OptNet (E2E)]] |
|---|---|---|---|
| **Decision logic** | Hand-coded weights + [[llm_providers\|GPT-4o]] | Learned linear/MLP scorer | Learned encoder + differentiable LP |
| **Training objective** | None | Pairwise ranking loss (RankNet/LambdaRank) | Financial regret (SPO+ / cvxpylayers KKT) |
| **Gradient computation** | N/A | Standard autograd through MLP | Implicit diff through $K_{\text{sym}}$, $O((n+2m+p)^2)$ |
| **Inference latency** | 7–12 s ([[llm_providers\|LLM]]-bound) | 1–10 ms (CPU) | 50–500 ms (LP solver + encoder) |
| **Training cost** | None | Low: CPU, $O(N \cdot n^2 \cdot d)$ nightly | High: GPU, $O(B \cdot (n+2m+p)^3)$ per step |
| **Handles MILP / split orders** | No | No | Yes (cvxpylayers LP / SPO+ MILP) |
| **Explainability** | High ([[llm_providers\|LLM]] justification string) | Medium (inspect $\mathbf{w}$) | Low — requires counterfactual + dual-var module |
| **Optimises business KPI directly** | No | No | Yes — see [[business_impact_metrics]] |
| **Adapts to buyer feedback** | No | Yes (see [[agent_memory_learning]]) | Yes |
| **Data requirement** | None | $\sim 5{,}000$ override events | $\sim 50{,}000$ closed records + $\mathbf{c}^{\text{true}}$ |
| **Cold-start** | Best (expert prior) | Weak (population mean) | Weakest |
| **Implementation risk** | Minimal | Low | High (KKT numerics, solver integration) |
| **Regulatory auditability** | Trivial — see [[security_compliance]] | Moderate | Requires dedicated explainability tooling |

---

## Engineering Transition Gating

### Phase 1 → [[phase2_learning_to_rank]]

Trigger on **any one** of:

- Override rate on Phase-1 recommendations exceeds **25%** sustained over a 90-day rolling window. Track via [[technical_performance_metrics]].
- Manual weight retuning requested by category leads for the **third time** in a calendar year.
- Accumulated labelled override events reach **5,000** in the [[audit_trail_system]].
- [[llm_providers|GPT-4o]] API cost for Phase-1 ReAct loop exceeds **₹50,000/month**. Monitor via [[business_impact_metrics]].

### [[phase2_learning_to_rank]] → [[phase3_optnet_e2e]]

Trigger on **any one** of:

- NDCG@5 of Phase-2 model plateaus (< 0.5% improvement over three consecutive monthly retraining cycles) while **realised financial regret** on holdout remains above Phase-1 baseline.
- Category management requests multi-supplier split orders — structurally incompatible with Phase-2's single argmax.
- Closed procurement records with ground-truth cost vectors reaches **50,000** in [[databases_postgresql_redis|PostgreSQL]].
- Decision-quality gap exceeds **15%** relative regret on holdout vs. oracle.

In no case should Phase 3 be deployed to buyers before:
1. A **shadow-mode evaluation** spanning at least one full fiscal quarter (monitored via [[observability_monitoring]]).
2. A **counterfactual explanation module** passes [[security_compliance|compliance review]].
3. A **Phase-1 fallback path** is operational on solver divergence or SLA breach.

---

## References

| Reference | Relevance |
|---|---|
| Burges et al. (2005). *Learning to Rank using Gradient Descent* (RankNet). ICML. | [[phase2_learning_to_rank]] — pairwise cross-entropy loss |
| Burges (2006). *Learning to Rank with Nonsmooth Cost Functions* (LambdaRank). NIPS. | [[phase2_learning_to_rank]] — NDCG-weighted lambda gradients |
| Burges et al. (2010). *From RankNet to LambdaRank to LambdaMART: An Overview*. MSR-TR-2010-82. | [[phase2_learning_to_rank]] — full mathematical derivation |
| Cao et al. (2007). *Learning to Rank: From Pairwise to Listwise* (ListNet). ICML. | [[phase2_learning_to_rank]] — listwise extension |
| Xia et al. (2008). *Listwise Approach to LTR* (ListMLE). ICML. | [[phase2_learning_to_rank]] — Plackett-Luce likelihood |
| Amos & Kolter (2017). *OptNet: Differentiable Optimization as a Layer*. ICML. | [[phase3_optnet_e2e]] — KKT differentiation |
| Agrawal et al. (2019). *Differentiable Convex Optimization Layers* (cvxpylayers). NeurIPS. | [[phase3_optnet_e2e]] — cone program layer |
| Elmachtoub & Grigas (2022). *Smart "Predict, then Optimize"* (SPO+). Management Science. | [[phase3_optnet_e2e]] — task loss, black-box subgradient |
| Berthet et al. (2020). *Learning with Differentiable Perturbed Optimizers*. NeurIPS. | [[phase3_optnet_e2e]] — MILP surrogate |
| Yao et al. (2023). *ReAct: Synergizing Reasoning and Acting in LLMs*. ICLR. | [[phase1_hybrid_react]] — ReAct agent pattern |
| Wang et al. (2018). *The LambdaLoss Framework*. CIKM. | [[phase2_learning_to_rank]] — theoretical grounding |
| Pineda et al. (2022). *Theseus: Differentiable Nonlinear Optimization*. NeurIPS. | [[phase3_optnet_e2e]] — nonconvex alternative |

---

*← Back to [[comparison_scoring_model]] | [[ai_models]] cluster*
