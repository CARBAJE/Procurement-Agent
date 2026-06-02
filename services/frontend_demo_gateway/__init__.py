"""Frontend Demo Gateway — dynamic mock for the Next.js demo client.

Exposes API endpoints with identical shapes to the static JSON mocks the
front-end previously consumed, but computes every response **dynamically**
using the real production components:

* ``POST /api/demo/score``      — runs the real ``Phase2Scorer`` PyTorch
                                  ``nn.Linear(3, 1)`` LTR model through the
                                  real ``core/features.py`` normaliser.
* ``POST /api/demo/negotiate``  — instantiates the real LangGraph
                                  StateGraph from the Negotiation Engine,
                                  including the deterministic 20% policy
                                  guardrail.
* ``GET  /api/demo/negotiate/{thread_id}`` — polling endpoint for the
                                  async resume cycle.

External infrastructure (live Beckn networks, Qdrant, Kafka, Redis) is
isolated through fast deterministic simulators inside the demo gateway —
nothing else about the math or state machinery is mocked.
"""
