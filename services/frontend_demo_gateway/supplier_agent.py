"""Supplier Agent — the autonomous LLM counter-party in the demo.

The buyer side is the production LangGraph Negotiation Engine (deterministic
strategy + hard policy guardrails). The *supplier* side is THIS agent: a real
LLM (``qwen3:8b`` by default) reached through Ollama's OpenAI-compatible API
via the official ``openai`` Python SDK.

Design contract:

* **Local Ollama only.** We construct ``AsyncOpenAI`` with the gateway's
  ``OLLAMA_BASE_URL`` (``http://localhost:11434/v1``) and ``OLLAMA_API_KEY``
  — never ``api.openai.com``, never a hardcoded key/model. The model comes
  from ``SUPPLIER_MODEL`` (config).
* **qwen3 emits ``<think>…</think>`` reasoning** before its answer. We strip
  it in :func:`_extract_json` before ``json.loads`` so the structured
  response survives.
* **Never throw.** A timeout, connection error, or unparseable completion
  degrades to a deterministic rule-based response (accept if the buyer's
  ask is within the configured discount floor, else counter at the floor).
  The demo must never hard-fail on a flaky model.

The agent is stateless across calls and is instantiated ONCE on
``app.state`` in the gateway lifespan — the ``AsyncOpenAI`` client owns a
connection pool that must not be recreated per request.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

SupplierAction = Literal["accept", "counter", "reject"]


# ─────────────────────────────────────────────────────────────────────────
# Response contract
# ─────────────────────────────────────────────────────────────────────────


class SupplierResponse(BaseModel):
    """Structured supplier turn, returned to the gateway and published to Redis."""

    action: SupplierAction = Field(..., description="accept | counter | reject")
    counter_price: Optional[float] = Field(
        default=None,
        description="Supplier's counter unit price (required for action=counter).",
    )
    proposed_delivery_date: Optional[str] = Field(
        default=None,
        description=(
            "Supplier's offered delivery date (ISO yyyy-mm-dd). Echoes the "
            "buyer's requested date when the supplier can meet it, or proposes "
            "a later date."
        ),
    )
    message: str = Field(
        default="",
        max_length=2000,
        description="Short natural-language justification (shown in the UI).",
    )
    model: str = Field(..., description="The model that produced this turn.")
    source: Literal["llm", "fallback"] = Field(
        default="llm",
        description="'llm' when qwen3 produced it, 'fallback' on degraded path.",
    )

    @field_validator("counter_price")
    @classmethod
    def _non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("counter_price must be positive")
        return v


# ─────────────────────────────────────────────────────────────────────────
# JSON extraction (strip qwen3 <think> blocks, then isolate the object)
# ─────────────────────────────────────────────────────────────────────────

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a qwen3 completion.

    qwen3 prefixes answers with a ``<think>…</think>`` reasoning trace and
    sometimes wraps the JSON in ```` ```json ```` fences. We strip the think
    block, then grab the outermost ``{…}`` span and parse it. Raises
    ``ValueError`` if nothing parseable is found (caller falls back).
    """
    if not text:
        raise ValueError("empty completion")
    cleaned = _THINK_RE.sub("", text).strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    match = _JSON_RE.search(cleaned)
    if not match:
        raise ValueError(f"no JSON object in completion: {cleaned[:160]!r}")
    return json.loads(match.group(0))


# ─────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a B2B supplier sales agent negotiating a procurement order. "
    "A corporate buyer is pushing for a lower unit price. Your job is to "
    "protect your margin while still closing the deal — you genuinely want "
    "the sale, but you do not give away discounts for free.\n\n"
    "Rules:\n"
    "- You hold a list (catalog) unit price. The buyer proposes a lower target price.\n"
    "- If the buyer's target is within a small, reasonable discount of your list "
    "price, ACCEPT.\n"
    "- If it is too aggressive, COUNTER with a price between the buyer's target and "
    "your list price — concede a little each round to signal good faith.\n"
    "- Only REJECT if the buyer's target is absurdly low or this is the final round "
    "and no agreement is reachable.\n"
    "- Concede more as rounds advance (time pressure works on you too).\n"
    "- You also negotiate the DELIVERY DATE: meet the buyer's requested delivery "
    "date when you reasonably can; otherwise propose the earliest realistic later "
    "date.\n\n"
    "Respond with ONLY a JSON object, no prose, in exactly this shape:\n"
    '{"action": "accept" | "counter" | "reject", '
    '"counter_price": <number or null>, '
    '"proposed_delivery_date": "<ISO yyyy-mm-dd date you can deliver by>", '
    '"message": "<one short sentence to the buyer>"}'
)


class SupplierAgent:
    """LLM supplier counter-party backed by a local Ollama model."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        acceptable_discount_floor: float = 0.08,
        temperature: float = 0.4,
        timeout_s: float = 60.0,
    ) -> None:
        # Single shared async client — owns a connection pool. Construct once
        # (per app lifespan), never per request.
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_s
        )
        self._model = model
        self._floor = acceptable_discount_floor
        self._temperature = temperature
        self._base_url = base_url

    @property
    def model(self) -> str:
        return self._model

    async def health(self) -> bool:
        """Lightweight readiness probe — can we list models on the daemon?"""
        try:
            await self._client.models.list()
            return True
        except Exception as exc:  # pragma: no cover — daemon down path
            logger.warning("Supplier Ollama health check failed: %s", exc)
            return False

    def _build_user_prompt(
        self,
        *,
        item: str,
        quantity: int,
        list_price: float,
        buyer_target_price: float,
        round_no: int,
        max_rounds: int,
        previous_offer: Optional[float],
        requested_delivery_date: Optional[str],
    ) -> str:
        discount = (
            (list_price - buyer_target_price) / list_price if list_price else 0.0
        )
        prior = ""
        if previous_offer is not None:
            prior = (
                f"In the previous round you offered {previous_offer:.2f} INR. "
                "The buyer has not accepted, so you MUST improve on that — your "
                "new counter has to be strictly lower than your previous offer "
                "(move closer to the buyer's target). Do not repeat the same price.\n"
            )
        delivery = ""
        if requested_delivery_date:
            delivery = (
                f"Buyer's requested delivery date: {requested_delivery_date}. "
                "State the delivery date you can commit to in proposed_delivery_date.\n"
            )
        return (
            f"Negotiation round {round_no} of {max_rounds}.\n"
            f"Item: {item}\n"
            f"Quantity: {quantity} units\n"
            f"Your list (catalog) unit price: {list_price:.2f} INR\n"
            f"Buyer's proposed target unit price: {buyer_target_price:.2f} INR "
            f"(a {discount * 100:.1f}% discount off your list price).\n"
            f"{delivery}"
            f"{prior}"
            "Decide your move and reply with the JSON object only."
        )

    async def respond(
        self,
        *,
        item: str,
        quantity: int,
        list_price: float,
        buyer_target_price: float,
        round_no: int = 1,
        max_rounds: int = 3,
        previous_offer: Optional[float] = None,
        requested_delivery_date: Optional[str] = None,
    ) -> SupplierResponse:
        """Produce the supplier's turn for the buyer's current counter-offer.

        Calls qwen3:8b through Ollama; on any failure degrades to a
        deterministic rule (accept within the discount floor, else counter
        at the floor price). Always returns a valid :class:`SupplierResponse`.
        """
        user_prompt = self._build_user_prompt(
            item=item,
            quantity=quantity,
            list_price=list_price,
            buyer_target_price=buyer_target_price,
            round_no=round_no,
            max_rounds=max_rounds,
            previous_offer=previous_offer,
            requested_delivery_date=requested_delivery_date,
        )
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = completion.choices[0].message.content or ""
            parsed = _extract_json(raw)
            return self._coerce(
                parsed,
                list_price=list_price,
                source="llm",
                requested_delivery_date=requested_delivery_date,
            )
        except Exception as exc:
            logger.warning(
                "Supplier LLM call failed (%s) — using deterministic fallback", exc
            )
            return self._fallback(
                list_price=list_price,
                buyer_target_price=buyer_target_price,
                round_no=round_no,
                max_rounds=max_rounds,
                requested_delivery_date=requested_delivery_date,
            )

    # ── helpers ──────────────────────────────────────────────────────────

    def _coerce(
        self,
        parsed: dict[str, Any],
        *,
        list_price: float,
        source: str,
        requested_delivery_date: Optional[str] = None,
    ) -> SupplierResponse:
        """Validate + clamp the model's JSON into a safe SupplierResponse."""
        action = str(parsed.get("action", "")).strip().lower()
        if action not in ("accept", "counter", "reject"):
            action = "counter"
        counter_price = parsed.get("counter_price")
        try:
            counter_price = float(counter_price) if counter_price is not None else None
        except (TypeError, ValueError):
            counter_price = None

        if action == "counter":
            # A counter must carry a price; never above list, never below 0.
            if counter_price is None or counter_price <= 0:
                counter_price = round(list_price * (1 - self._floor), 2)
            counter_price = min(counter_price, list_price)
        else:
            counter_price = None

        # Delivery: trust a plausible ISO-ish date from the model, else echo the
        # buyer's requested date (supplier meets it).
        proposed_delivery = parsed.get("proposed_delivery_date")
        if not isinstance(proposed_delivery, str) or not proposed_delivery.strip():
            proposed_delivery = requested_delivery_date
        elif proposed_delivery.strip().lower() in ("same as requested", "same"):
            proposed_delivery = requested_delivery_date
        else:
            proposed_delivery = proposed_delivery.strip()

        message = str(parsed.get("message", "")).strip()[:2000]
        return SupplierResponse(
            action=action,  # type: ignore[arg-type]
            counter_price=counter_price,
            proposed_delivery_date=proposed_delivery,
            message=message or f"Supplier {action}.",
            model=self._model,
            source=source,  # type: ignore[arg-type]
        )

    def _fallback(
        self,
        *,
        list_price: float,
        buyer_target_price: float,
        round_no: int,
        max_rounds: int,
        requested_delivery_date: Optional[str] = None,
    ) -> SupplierResponse:
        """Deterministic rule when the LLM is unavailable/unparseable."""
        floor_price = list_price * (1 - self._floor)
        if buyer_target_price >= floor_price:
            return SupplierResponse(
                action="accept",
                counter_price=None,
                proposed_delivery_date=requested_delivery_date,
                message=(
                    "Your target is within our acceptable range — we accept."
                ),
                model=self._model,
                source="fallback",
            )
        if round_no >= max_rounds:
            # Final round: meet at the floor rather than walk away.
            return SupplierResponse(
                action="counter",
                counter_price=round(floor_price, 2),
                proposed_delivery_date=requested_delivery_date,
                message="Final offer: this is the lowest we can go.",
                model=self._model,
                source="fallback",
            )
        # Split the difference between buyer target and our floor.
        midpoint = round((buyer_target_price + floor_price) / 2, 2)
        return SupplierResponse(
            action="counter",
            counter_price=midpoint,
            proposed_delivery_date=requested_delivery_date,
            message="We can come down, but not that far — here is our counter.",
            model=self._model,
            source="fallback",
        )


__all__ = ["SupplierAgent", "SupplierResponse", "_extract_json"]
