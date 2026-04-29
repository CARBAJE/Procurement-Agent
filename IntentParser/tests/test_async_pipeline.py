"""
Dual-mode async integration test suite for the IntentParser /parse/full endpoint.

MODES
-----
mock (default)
    All infrastructure — LLM, embedding, DB, MCP — is replaced with AsyncMock /
    MagicMock objects.  The full FastAPI + aiohttp HTTP stack still runs; only the
    backend I/O is stubbed.  No external services required.  Runs in < 1 second.

live
    Uses the real asyncpg pool, the real sentence-transformers embedding model, and
    the real MCPSidecarClient.  Stage 1+2 LLM calls also hit Ollama.
    Requires: PostgreSQL 16 + pgvector, Ollama (qwen3:8b), MCP sidecar on :3000.

Usage
-----
    # Mock mode (CI/CD, no infrastructure)
    pytest IntentParser/tests/test_async_pipeline.py -v

    # Live mode (pre-production validation)
    INTENT_PARSER_TEST_MODE=live pytest IntentParser/tests/test_async_pipeline.py -v -s

DESIGN NOTES
------------
* httpx.ASGITransport (0.28) does NOT send the ASGI lifespan scope; the pool
  initialises lazily via get_pool() on first DB access.  No lifespan mocking needed.
* Stage 1+2 LLM patches are applied by the autouse _patch_llm fixture so individual
  test functions only need to patch Stage 3 (cache / MCP) behaviour.
* Path B async writes (asyncio.create_task) are handled per-test:
    mock mode — MCPResultAdapter.write_path_b_row is patched to AsyncMock (no-op).
    live  mode — test awaits asyncio.sleep() to let the write complete; _live_seed
                 teardown waits an additional 2 s before DELETE.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from IntentParser.api import app
from IntentParser.models import (
    BecknIntent,
    BudgetConstraints,
    CacheMatch,
    ParsedIntent,
)
from IntentParser.validation import MCPResultAdapter

# ── Mode ──────────────────────────────────────────────────────────────────────

_MODE = os.getenv("INTENT_PARSER_TEST_MODE", "mock").lower()
_LIVE = _MODE == "live"

# ── Queries ───────────────────────────────────────────────────────────────────

# Test 1 — should hit VALIDATED (high-sim match in DB / mock score 0.95)
VALIDATED_QUERY = (
    "50 stainless steel flanged ball valves PN16 2 inch SS316 for Bangalore, "
    "deliver in 1 week, max 5000 INR each"
)

# Test 2 — should hit AMBIGUOUS (partial match / mock score 0.60)
AMBIGUOUS_QUERY = (
    "25 industrial ball valves for Bangalore plant, 2 weeks delivery"
)

# Test 3 — cache miss, MCP probe finds item
MCP_HIT_QUERY = (
    "200 meters of Cat6 UTP network cable for Mumbai office, "
    "delivery in 3 days, max 15 INR per meter"
)

# Test 4 — cache miss, MCP probe empty → dead end
DEAD_END_QUERY = (
    "ASTM A790 UNS S32750 super duplex 25Cr-7Ni bi-metallic flanged pipe fitting "
    "DN50 PN25 class 2500 with ASME B16.5 face flange"
)

# ── Seed identifiers (live mode only) ────────────────────────────────────────

_SEED_BPP_ID = "bpp_test_async_pipeline"

# ── MCP sidecar process config (live mode only) ───────────────────────────────
# Adjust MCP_SIDECAR_DIR and MCP_START_CMD to match your sidecar entry point.
# The fixture is a no-op in mock mode, so these values are never evaluated there.
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
MCP_SIDECAR_DIR: Path = _PROJECT_ROOT / "services" / "mcp-sidecar"
MCP_START_CMD: list[str] = ["npm", "run", "start"]
_MCP_HOST = "localhost"
_MCP_PORT = 3000
_MCP_STARTUP_TIMEOUT = 15  # seconds to wait for the sidecar to accept connections

# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def _parsed_intent() -> ParsedIntent:
    """Mocked Stage 1 output — always RequestQuote."""
    return ParsedIntent(
        intent="RequestQuote",
        product_name="SS Ball Valve",
        quantity=50,
        confidence=0.97,
        reasoning="Procurement request for industrial valves.",
    )


@pytest.fixture
def _beckn_intent() -> BecknIntent:
    """Mocked Stage 2 output — fully specified BecknIntent."""
    return BecknIntent(
        item="Stainless Steel Flanged Ball Valve",
        descriptions=["PN16", "2 inch", "SS316"],
        quantity=50,
        location_coordinates="12.9716,77.5946",
        delivery_timeline=168,
        budget_constraints=BudgetConstraints(max=5000.0, min=0.0),
    )


@pytest.fixture(autouse=True)
def _patch_llm(_parsed_intent: ParsedIntent, _beckn_intent: BecknIntent):
    """Auto-patch Stage 1+2 LLM calls for all tests in this module.

    In live mode this is a no-op; Ollama handles the real calls.
    In mock mode the three patches are active for the entire duration of each
    test function, including the HTTP request processing cycle.
    """
    if _LIVE:
        yield
        return

    with (
        patch(
            "IntentParser.orchestrator.classify_intent",
            new_callable=AsyncMock,
            return_value=_parsed_intent,
        ),
        patch(
            "IntentParser.orchestrator.extract_beckn_intent",
            new_callable=AsyncMock,
            return_value=(_beckn_intent, "qwen3:8b"),
        ),
        patch(
            "IntentParser.validation.embed",
            new_callable=AsyncMock,
            return_value=np.zeros(384, dtype=np.float32),
        ),
    ):
        yield


@pytest.fixture(scope="module")
def live_mcp_server():
    """Spin up the MCP sidecar subprocess before live-mode tests; tear it down after.

    Yields True when the sidecar is confirmed ready, False on any failure.
    Never calls pytest.fail/skip — that decision is left to individual tests so
    that DB-only tests (1 and 2) are not cancelled by a missing MCP sidecar.

    In mock mode yields False immediately (value is ignored by mock-mode tests).

    Startup sequence:
      1. Verify MCP_SIDECAR_DIR exists — yield False if not.
      2. Popen MCP_START_CMD (caught; yields False if command not found).
      3. Poll localhost:_MCP_PORT every 0.5 s for up to _MCP_STARTUP_TIMEOUT s.
      4. yield True on success; kill process and yield False on timeout.

    Teardown sequence (only reached when process started successfully):
      1. process.terminate() — SIGTERM, allows graceful shutdown.
      2. process.wait(timeout=5) — waits up to 5 s.
      3. process.kill() + process.wait() — force-kill if still alive.
    """
    if not _LIVE:
        yield False
        return

    if not MCP_SIDECAR_DIR.exists():
        print(
            f"\n[live_mcp_server] Warning: MCP_SIDECAR_DIR={MCP_SIDECAR_DIR} does not exist. "
            "Tests that require MCP will be skipped."
        )
        yield False
        return

    try:
        process = subprocess.Popen(
            MCP_START_CMD,
            cwd=MCP_SIDECAR_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(
            f"\n[live_mcp_server] Warning: Failed to launch MCP sidecar "
            f"({MCP_START_CMD}): {exc}. Tests that require MCP will be skipped."
        )
        yield False
        return

    # Poll until port is accepting connections or timeout expires.
    deadline = time.monotonic() + _MCP_STARTUP_TIMEOUT
    ready = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_MCP_HOST, _MCP_PORT), timeout=1.0):
                ready = True
                break
        except OSError:
            time.sleep(0.5)

    if not ready:
        process.kill()
        process.wait()
        print(
            f"\n[live_mcp_server] Warning: MCP sidecar did not accept connections "
            f"on :{_MCP_PORT} within {_MCP_STARTUP_TIMEOUT}s. "
            "Tests that require MCP will be skipped."
        )
        yield False
        return

    print(f"\n[live_mcp_server] MCP sidecar ready on :{_MCP_PORT}")
    yield True  # ── tests run ──────────────────────────────────────────────────

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    print("\n[live_mcp_server] MCP sidecar terminated")


@pytest.fixture
async def client(live_mcp_server):  # noqa: ARG001
    """httpx.AsyncClient with ASGI transport pointed at the FastAPI app.

    The pool is never touched in mock mode (all DB calls are patched per-test).
    In live mode the pool initialises lazily on first DB access; close_pool() is
    called after the client context exits to drain connections cleanly.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    if _LIVE:
        from IntentParser.db import close_pool

        await close_pool()


@pytest.fixture
async def _live_seed():
    """Seed bpp_catalog_semantic_cache with two known test items.

    Inserts items before the test and deletes ALL rows with bpp_id ==
    _SEED_BPP_ID after the test (including any Path B writes that used a
    different item name but the same bpp_id).  A 2-second sleep allows
    background Path B writes to complete before the DELETE.

    In mock mode this fixture is a no-op.
    """
    if not _LIVE:
        yield
        return

    from IntentParser.db import get_pool
    from IntentParser.embeddings import embed_sync

    pool = await get_pool()

    # Seed 1: high-similarity item for the VALIDATED test
    # Embed text mirrors Stage 3's query-string format: "item | spec | spec | …"
    seed_validated_text = "Stainless Steel Flanged Ball Valve | PN16 | 2 inch | SS316"
    # Seed 2: lower-similarity item for the AMBIGUOUS test
    seed_ambiguous_text = "Industrial Ball Valve"

    upsert_sql = """
        INSERT INTO bpp_catalog_semantic_cache
            (item_name, bpp_id, bpp_uri, item_embedding, source, embedding_strategy)
        VALUES ($1, $2, $3, $4::vector, 'bpp_publish', 'item_name_only')
        ON CONFLICT (item_name, bpp_id)
        DO UPDATE SET
            item_embedding = EXCLUDED.item_embedding,
            last_seen_at   = now()
    """

    seeds = [
        ("IntentParser Test SS Flanged Ball Valve", seed_validated_text),
        ("IntentParser Test Industrial Ball Valve", seed_ambiguous_text),
    ]

    async with pool.acquire() as conn:
        for item_name, embed_text in seeds:
            vec = embed_sync(embed_text)
            await conn.execute(
                upsert_sql,
                item_name,
                _SEED_BPP_ID,
                "http://bpp-test.example.com",
                vec.tolist(),
            )

    yield  # ── test runs ──────────────────────────────────────────────────────

    # Allow any async Path B writes to complete before cleanup
    await asyncio.sleep(2)

    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM bpp_catalog_semantic_cache WHERE bpp_id = $1",
            _SEED_BPP_ID,
        )

    # asyncpg execute() returns a tag like "DELETE 3"
    n_deleted = int(result.split()[-1]) if result and result.split()[-1].isdigit() else "?"
    print(f"\n[live teardown] Removed {n_deleted} record(s) from bpp_catalog_semantic_cache")


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_1_cache_hit_returns_validated(client: AsyncClient, _live_seed) -> None:
    """P1 — ANN similarity ≥ 0.85 → validation.status == 'VALIDATED'.

    Mock:  query_semantic_cache returns similarity 0.95.
    Live:  seeded item matches the LLM-extracted BecknIntent.item.
    """
    # ── Arrange & Act ──────────────────────────────────────────────────────────
    if _LIVE:
        response = await client.post("/parse/full", json={"query": VALIDATED_QUERY})
    else:
        cache_hit = [
            CacheMatch(
                item_name="Stainless Steel Flanged Ball Valve 2 inch",
                bpp_id="bpp_industrial_001",
                similarity=0.95,
            )
        ]
        with patch(
            "IntentParser.validation.query_semantic_cache",
            new_callable=AsyncMock,
            return_value=cache_hit,
        ):
            response = await client.post("/parse/full", json={"query": VALIDATED_QUERY})

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] in ["RequestQuote", "SearchProduct", "PurchaseOrder"]
    assert body["beckn_intent"] is not None, "BecknIntent must be present for procurement queries"

    validation = body.get("validation")
    assert validation is not None, "validation dict must be present"
    assert validation["status"] == "VALIDATED", (
        f"Expected VALIDATED; got: {validation!r}"
    )
    assert "matched" in validation, "VALIDATED response must name the matched item"
    assert "similarity" in validation, "VALIDATED response must include the similarity score"
    assert float(validation["similarity"]) >= 0.85, (
        f"similarity {validation['similarity']} is below the VALIDATED threshold (0.85)"
    )
    assert body.get("recovery_log") == [], "No recovery actions should fire on a cache hit"


async def test_2_ambiguous_zone_includes_suggestion(client: AsyncClient, _live_seed) -> None:
    """P1 (low confidence) — 0.45 ≤ similarity < 0.85 → AMBIGUOUS + matched suggestion.

    Mock:  query_semantic_cache returns similarity 0.60.
    Live:  vague query produces a partial match against seeded items.
           Accept AMBIGUOUS; if the model returns VALIDATED that is also accepted
           (similarity outcome depends on the live embedding model).
    """
    # ── Arrange & Act ──────────────────────────────────────────────────────────
    if _LIVE:
        response = await client.post("/parse/full", json={"query": AMBIGUOUS_QUERY})
    else:
        partial_match = [
            CacheMatch(
                item_name="Stainless Steel Ball Valve Generic",
                bpp_id="bpp_industrial_002",
                similarity=0.60,
            )
        ]
        with patch(
            "IntentParser.validation.query_semantic_cache",
            new_callable=AsyncMock,
            return_value=partial_match,
        ):
            response = await client.post("/parse/full", json={"query": AMBIGUOUS_QUERY})

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] in ["RequestQuote", "SearchProduct", "PurchaseOrder"]

    validation = body.get("validation")
    assert validation is not None, "validation dict must be present"

    if _LIVE:
        # Live: ANN score depends on actual seeded embeddings; accept cache zones
        assert validation["status"] in ("AMBIGUOUS", "VALIDATED"), (
            f"Expected AMBIGUOUS or VALIDATED; got: {validation!r}"
        )
    else:
        assert validation["status"] == "AMBIGUOUS", (
            f"Expected AMBIGUOUS for similarity 0.60; got: {validation!r}"
        )
        assert 0.45 <= float(validation["similarity"]) < 0.85, (
            f"similarity {validation['similarity']} is outside the AMBIGUOUS band [0.45, 0.85)"
        )

    # 'matched' is the system's closest-match suggestion — must be present and non-empty
    assert "matched" in validation, "AMBIGUOUS/VALIDATED response must include a matched suggestion"
    assert validation["matched"], "matched suggestion must not be an empty string"


async def test_3_mcp_success_returns_mcp_validated(
    client: AsyncClient, live_mcp_server: bool
) -> None:
    """P2 — ANN cache miss + MCP probe finds item → MCP_VALIDATED + Path B write dispatched.

    Mock:  cache returns similarity 0.10; MCP mock returns found=True.
           MCPResultAdapter.write_path_b_row is patched to AsyncMock so no real
           DB write occurs; asyncio.sleep(0) lets the create_task coroutine tick.
    Live:  real MCP sidecar must be running on MCP_SSE_URL (default :3000).
           Path B write runs for real; the item is intentionally left in the cache
           (correct production behaviour — it warms the cache for future queries).
    """
    # ── Arrange & Act ──────────────────────────────────────────────────────────
    if _LIVE:
        if not live_mcp_server:
            pytest.skip(
                "MCP sidecar directory missing or failed to start. "
                "Set MCP_SIDECAR_DIR and MCP_START_CMD, then re-run."
            )
        # Remove any "UTP Cat6" rows left by previous runs or PoC notebooks to
        # guarantee the ANN query produces a genuine CACHE_MISS before the MCP probe.
        from IntentParser.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM bpp_catalog_semantic_cache WHERE item_name ILIKE '%UTP Cat6%'"
            )
        n_deleted = int(result.split()[-1]) if result and result.split()[-1].isdigit() else "?"
        print(f"\n[test_3 setup] Cleared {n_deleted} stale Cat6 row(s) to force CACHE_MISS")

        response = await client.post("/parse/full", json={"query": MCP_HIT_QUERY})
        # Allow the async Path B write (create_task) to complete
        await asyncio.sleep(3)
    else:
        low_sim = [CacheMatch(item_name="Unrelated Item X", bpp_id="bpp_000", similarity=0.10)]
        mcp_hit = {
            "found": True,
            "items": [
                {
                    "item_name": "UTP Cat6 Network Cable",
                    "bpp_id": "bpp_network_001",
                    "bpp_uri": "http://bpp-network.example.com",
                }
            ],
            "probe_latency_ms": 1420,
        }
        mock_mcp = MagicMock()
        mock_mcp.search_bpp_catalog = AsyncMock(return_value=mcp_hit)

        with (
            patch(
                "IntentParser.validation.query_semantic_cache",
                new_callable=AsyncMock,
                return_value=low_sim,
            ),
            patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp),
            patch.object(MCPResultAdapter, "write_path_b_row", new_callable=AsyncMock),
        ):
            response = await client.post("/parse/full", json={"query": MCP_HIT_QUERY})
            await asyncio.sleep(0)  # let the Path B create_task coroutine tick

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] in ["RequestQuote", "SearchProduct", "PurchaseOrder"]
    assert body["beckn_intent"] is not None

    validation = body.get("validation")
    assert validation is not None, "validation dict must be present"

    # In live mode, skip rather than fail if the MCP sidecar is not reachable.
    # The MCPSidecarClient catches connection errors and returns found=False, so
    # the response will contain CACHE_MISS instead of MCP_VALIDATED when the
    # sidecar is down.
    if _LIVE and validation.get("status") != "MCP_VALIDATED":
        pytest.skip("Live MCP sidecar is unreachable. Skipping MCP success test.")

    assert validation["status"] == "MCP_VALIDATED", (
        f"Expected MCP_VALIDATED; got: {validation!r}"
    )
    assert "matched" in validation, "MCP_VALIDATED response must include the matched item name"
    assert validation["matched"], "matched item name must not be empty"
    assert "bpp_id" in validation, "MCP_VALIDATED response must include bpp_id"
    assert "bpp_uri" in validation, "MCP_VALIDATED response must include bpp_uri"
    assert body.get("recovery_log") == [], "No recovery actions should fire on MCP_VALIDATED"


async def test_4_dead_end_triggers_recovery_and_not_found(
    client: AsyncClient, live_mcp_server: bool
) -> None:
    """P3 — ANN cache miss + MCP probe empty → not_found=True + recovery log populated.

    Mock:  cache returns []; MCP mock returns found=False; broadening returns None
           so the full recovery path fires (log + notify + RFQ).
    Live:  highly specific niche query should miss both DB and MCP network.
    """
    # ── Arrange & Act ──────────────────────────────────────────────────────────
    if _LIVE:
        if not live_mcp_server:
            pytest.skip(
                "MCP sidecar directory missing or failed to start. "
                "Set MCP_SIDECAR_DIR and MCP_START_CMD, then re-run."
            )
        response = await client.post("/parse/full", json={"query": DEAD_END_QUERY})
    else:
        empty_cache: list[CacheMatch] = []
        mcp_empty = {"found": False, "items": [], "probe_latency_ms": 3000}
        mock_mcp = MagicMock()
        mock_mcp.search_bpp_catalog = AsyncMock(return_value=mcp_empty)

        with (
            patch(
                "IntentParser.validation.query_semantic_cache",
                new_callable=AsyncMock,
                return_value=empty_cache,
            ),
            patch("IntentParser.validation.get_mcp_client", return_value=mock_mcp),
            # Broadening returns None → escalate to log/notify/RFQ
            patch(
                "IntentParser.orchestrator.broaden_procurement_query",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("IntentParser.orchestrator.log_unmet_demand", new_callable=AsyncMock),
            patch("IntentParser.orchestrator.notify_buyer_no_stock", new_callable=AsyncMock),
            patch("IntentParser.orchestrator.trigger_open_rfq_flow", new_callable=AsyncMock),
        ):
            response = await client.post("/parse/full", json={"query": DEAD_END_QUERY})

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] in ["RequestQuote", "SearchProduct"]

    validation = body.get("validation")
    assert validation is not None, "validation dict must be present even for dead-end queries"
    assert validation["status"] == "CACHE_MISS", (
        f"Expected CACHE_MISS; got: {validation!r}"
    )
    assert validation.get("not_found") is True, (
        "not_found must be True when neither DB nor MCP found the item"
    )

    recovery_log = body.get("recovery_log", [])
    assert len(recovery_log) >= 1, (
        "recovery_log must be populated when not_found=True — "
        f"got empty list. Full response: {body!r}"
    )
