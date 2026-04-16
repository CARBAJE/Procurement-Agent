"""NL Intent Parser — converts free-form procurement text to SearchIntent.

Uses Claude via tool_choice={"type": "tool"} to guarantee structured JSON output.
The tool schema maps directly to SearchIntent fields so no ambiguous post-processing.

Usage:
    parser = IntentParser(api_key="sk-ant-...")
    intent = await parser.parse("500 reams A4 paper, Bangalore, 3 days, budget 1 lakh")
"""
from __future__ import annotations

import anthropic

from ..beckn.models import (
    Descriptor,
    Fulfillment,
    FulfillmentEnd,
    GPSLocation,
    ItemQuantity,
    Payment,
    PaymentParams,
    SearchIntent,
    SearchItem,
    TimeConstraint,
)
from .city_gps import resolve_gps
from .prompts import FEW_SHOT, SYSTEM_PROMPT

# ── Tool schema ───────────────────────────────────────────────────────────────

_TOOL = {
    "name": "parse_procurement_intent",
    "description": "Extract structured procurement intent from a natural language request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "item_name": {
                "type": "string",
                "description": "Name/description of the item to procure",
            },
            "quantity": {
                "type": "integer",
                "description": "Number of units required",
            },
            "unit": {
                "type": "string",
                "description": "Unit of measure (units, reams, kits, pairs, etc.)",
                "default": "units",
            },
            "delivery_city": {
                "type": "string",
                "description": "City name for delivery location",
            },
            "delivery_gps": {
                "type": "string",
                "description": "GPS coordinates 'lat,lng' if explicitly provided",
            },
            "delivery_days": {
                "type": "integer",
                "description": "Number of business days for delivery",
            },
            "budget_amount": {
                "type": "string",
                "description": "Budget as a plain numeric string (no symbols)",
            },
            "budget_currency": {
                "type": "string",
                "default": "INR",
                "description": "Currency code",
            },
            "is_urgent": {
                "type": "boolean",
                "default": False,
                "description": "True if the request is flagged as urgent/emergency",
            },
            "specifications": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Technical specifications (RAM, certifications, grades, etc.)",
            },
        },
        "required": ["item_name", "quantity"],
    },
}

# ── Duration helper ───────────────────────────────────────────────────────────


def _days_to_iso_duration(days: int) -> str:
    """Convert a number of days to an ISO 8601 duration string."""
    if days < 1:
        return "PT1H"
    if days == 1:
        return "P1D"
    return f"P{days}D"


# ── Parser ────────────────────────────────────────────────────────────────────


class IntentParser:
    """Async LLM-backed parser that converts natural language to SearchIntent."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def parse(self, text: str) -> SearchIntent:
        """Parse a natural language procurement request into a SearchIntent.

        Raises:
            ValueError: if the LLM response does not contain a valid tool call.
        """
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "parse_procurement_intent"},
            messages=[
                *FEW_SHOT,
                {"role": "user", "content": text},
            ],
        )

        tool_input = self._extract_tool_input(response)
        return self._build_intent(tool_input)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract_tool_input(self, response: anthropic.types.Message) -> dict:
        for block in response.content:
            if block.type == "tool_use" and block.name == "parse_procurement_intent":
                return block.input
        raise ValueError(
            f"LLM did not return a parse_procurement_intent tool call. "
            f"Response: {response}"
        )

    def _build_intent(self, data: dict) -> SearchIntent:
        # ── Item ──────────────────────────────────────────────────────────────
        item_name = data["item_name"]
        specs = data.get("specifications", [])
        if specs:
            short_desc = "; ".join(specs)
            descriptor = Descriptor(name=item_name, short_desc=short_desc)
        else:
            descriptor = Descriptor(name=item_name)

        quantity = data.get("quantity")
        search_item = SearchItem(
            descriptor=descriptor,
            quantity=ItemQuantity(count=quantity) if quantity else None,
        )

        # ── Fulfillment ───────────────────────────────────────────────────────
        gps = data.get("delivery_gps") or resolve_gps(data.get("delivery_city"))
        days = data.get("delivery_days")

        fulfillment = None
        if gps or days:
            fulfillment = Fulfillment(
                end=FulfillmentEnd(
                    location=GPSLocation(gps=gps) if gps else GPSLocation(gps="0,0"),
                    time=TimeConstraint(duration=_days_to_iso_duration(days))
                    if days
                    else None,
                )
            )

        # ── Payment ───────────────────────────────────────────────────────────
        budget = data.get("budget_amount")
        payment = None
        if budget:
            payment = Payment(
                params=PaymentParams(
                    amount=str(budget),
                    currency=data.get("budget_currency", "INR"),
                )
            )

        return SearchIntent(
            item=search_item,
            fulfillment=fulfillment,
            payment=payment,
        )
