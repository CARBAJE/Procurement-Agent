"""Discovery Engine — Phase 3 multi-network search microservice.

Fans out a single ``BecknIntent`` to N independent Beckn networks in
parallel via ``asyncio.gather``, enforces per-network timeouts +
circuit breakers, and aggregates returned catalogs into a single
deduplicated result set. Implements the *Multi-Network Search*
deliverable from
``KnowledgeBase/project_scaffold/milestones/phase3_advanced_intelligence_enterprise_features.md``.
"""
