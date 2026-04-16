from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

import instructor
from openai import OpenAI

from .schemas import BecknIntent, ParsedIntent, ParseResult

# ── Config ────────────────────────────────────────────────────────────────────

COMPLEX_MODEL = os.getenv("COMPLEX_MODEL", "qwen3:8b")
SIMPLE_MODEL  = os.getenv("SIMPLE_MODEL",  "qwen3:1.7b")

_client = instructor.from_openai(
    OpenAI(base_url=os.getenv("OLLAMA_URL", "http://localhost:11434/v1"), api_key="ollama"),
    mode=instructor.Mode.JSON,
)

# ── Prompts ───────────────────────────────────────────────────────────────────

_INTENT_PROMPT = """
You are an intent classifier for a Beckn-based procurement system.
Classify the user query into a PascalCase intent (e.g. SearchProduct, RequestQuote, TrackOrder, CancelOrder).
Domain: users search for industrial products, request quotes (RFQ), and manage orders on a decentralized Beckn network.
""".strip()

_BECKN_PROMPT = """
You are a procurement data extractor for the Beckn protocol. Extract structured data from the user query.
- descriptions: all technical specs (e.g. "80gsm", "A4", "Cat6", "2 inch")
- delivery_timeline: convert to hours — 1 day=24h, 1 week=168h
- budget: numeric values only, no currency symbols; if only upper bound given, set min=0
- location lookup: Bangalore/Bengaluru=12.9716,77.5946 | Mumbai=19.0760,72.8777 |
  Delhi=28.7041,77.1025 | Chennai=13.0827,80.2707 | Hyderabad=17.3850,78.4867 |
  Pune=18.5204,73.8567 | Kolkata=22.5726,88.3639 | unknown city → raw text
""".strip()

# ── Routing heuristic ─────────────────────────────────────────────────────────

_COMPLEX_KEYWORDS = frozenset({
    "delivery", "deliver", "timeline", "deadline", "days", "weeks", "hours", "within",
    "budget", "price", "cost", "rupee", "rupees", "inr", "usd",
    "per unit", "per sheet", "per meter", "under", "maximum", "max",
})


def _is_complex(query: str) -> bool:
    lower = query.lower()
    return (
        len(query) > 120
        or len(re.findall(r"\b\d+(?:\.\d+)?\b", query)) >= 2
        or any(kw in lower for kw in _COMPLEX_KEYWORDS)
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

_PROCUREMENT_INTENTS = frozenset({"SearchProduct", "RequestQuote", "PurchaseOrder"})


def _chat(model: str, prompt: str, query: str, schema):
    return _client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": query}],
        response_model=schema,
        max_retries=3,
    )


def _parse_beckn(query: str) -> tuple[BecknIntent, str]:
    model = COMPLEX_MODEL if _is_complex(query) else SIMPLE_MODEL
    try:
        return _chat(model, _BECKN_PROMPT, query, BecknIntent), model
    except Exception:
        if model == SIMPLE_MODEL:
            return _chat(COMPLEX_MODEL, _BECKN_PROMPT, query, BecknIntent), COMPLEX_MODEL
        raise

# ── Pipeline ──────────────────────────────────────────────────────────────────

def parse_request(query: str) -> ParseResult:
    intent = _chat(COMPLEX_MODEL, _INTENT_PROMPT, query, ParsedIntent)
    if intent.intent not in _PROCUREMENT_INTENTS:
        return ParseResult(intent=intent.intent, confidence=intent.confidence)
    beckn, model = _parse_beckn(query)
    return ParseResult(intent=intent.intent, confidence=intent.confidence, beckn_intent=beckn, routed_to=model)


def parse_batch(queries: list[str], max_workers: int = 4) -> list[ParseResult]:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(parse_request, queries))
