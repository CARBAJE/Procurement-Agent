"""Negotiation Engine — Phase 3 microservice (skeleton).

Implements the LangGraph state machine, deterministic policy guardrails, and
Pydantic data contracts specified by the architecture cluster at
``KnowledgeBase/project_scaffold/architecture/negotiation_engine/``.

This package currently ships the topology + guardrail layer only. LLM calls,
Redis Pub/Sub transport, and the Postgres-backed checkpointer are introduced
in subsequent implementation steps.
"""
