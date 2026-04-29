"""Centralized configuration — all tunable constants in one place."""
from __future__ import annotations

import os

# ── LLM / Ollama ──────────────────────────────────────────────────────────────

OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
COMPLEX_MODEL: str = os.getenv("COMPLEX_MODEL", "qwen3:8b")
SIMPLE_MODEL: str = os.getenv("SIMPLE_MODEL", "qwen3:1.7b")

# ── Embeddings ────────────────────────────────────────────────────────────────

EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM: int = 384

# ── Validation thresholds (calibrated for all-MiniLM-L6-v2 / cosine) ─────────

VALIDATED_THRESHOLD: float = 0.85
AMBIGUOUS_THRESHOLD: float = 0.45

# ── Claude fallback (last resort) ─────────────────────────────────────────────

CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_FALLBACK_ENABLED: bool = bool(ANTHROPIC_API_KEY)

# ── MCP sidecar ───────────────────────────────────────────────────────────────

MCP_SSE_URL: str = os.getenv("MCP_SSE_URL", "http://localhost:3000/sse")
MCP_PROBE_TIMEOUT: float = float(os.getenv("MCP_PROBE_TIMEOUT", "8"))

# Beckn protocol parameters passed to the sidecar's search_bpp_catalog tool.
# Defaults here; override per-deployment for non-procurement domains.
BECKN_DOMAIN: str = os.getenv("BECKN_DOMAIN", "procurement")
BECKN_VERSION: str = os.getenv("BECKN_VERSION", "1.1.0")

# ── PostgreSQL / asyncpg pool ─────────────────────────────────────────────────

DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
DB_NAME: str = os.getenv("DB_NAME", "procurement_agent")
DB_USER: str = os.getenv("DB_USER", "carbaje")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
DB_SSL: str = os.getenv("DB_SSL", "prefer")
DB_MIN_POOL: int = int(os.getenv("DB_MIN_POOL", "5"))
DB_MAX_POOL: int = int(os.getenv("DB_MAX_POOL", "20"))
DB_CMD_TIMEOUT: float = float(os.getenv("DB_CMD_TIMEOUT", "5.0"))
HNSW_EF_SEARCH: int = int(os.getenv("HNSW_EF_SEARCH", "100"))

# ── Gate ──────────────────────────────────────────────────────────────────────

PROCUREMENT_INTENTS: frozenset[str] = frozenset(
    {"SearchProduct", "RequestQuote", "PurchaseOrder"}
)
