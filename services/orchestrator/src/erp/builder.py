"""Build a vendor-neutral NormalizedPO payload (as dict) from the orchestrator
session state at /commit time.

The shape mirrors services/erp-adapter/src/models.py::NormalizedPO. We emit a
plain dict (no Pydantic on the orchestrator side) — the adapter validates.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def build_normalized_po(
    *,
    state: dict[str, Any],
    chosen: dict[str, Any],
    intent: dict[str, Any],
    order_id: str,
    contract_id: str | None,
    payment_terms: dict[str, Any],
    fulfillment_eta: str | None,
    budget_hold_id: str | None,
    # Buyer info passed in explicitly — workflow.py builds the dict from env
    buyer: dict[str, Any],
) -> dict[str, Any]:
    txn_id = state.get("transaction_id") or state.get("intent", {}).get("transaction_id") or ""
    quantity = int(intent.get("quantity") or 1)
    currency = chosen.get("price_currency") or "INR"
    unit_price = chosen.get("price_value") or "0"
    try:
        subtotal = (Decimal(str(unit_price)) * Decimal(quantity)).quantize(Decimal("0.01"))
    except Exception:
        subtotal = Decimal("0.00")

    return {
        "transaction_id": txn_id,
        "order_id": order_id,
        "contract_id": contract_id,
        "buyer": buyer,
        "supplier": {
            "bpp_id": chosen.get("bpp_id"),
            "bpp_uri": chosen.get("bpp_uri"),
            "name": chosen.get("provider_name") or chosen.get("provider_id"),
        },
        "line_items": [{
            "item_id": chosen.get("item_id"),
            "name": chosen.get("item_name"),
            "quantity": quantity,
            "unit": "each",
            "unit_price": str(unit_price),
            "currency": currency,
            "category": intent.get("category"),
        }],
        "totals": {
            "subtotal": str(subtotal),
            "currency": currency,
        },
        "payment_terms": {
            "type": payment_terms.get("type"),
            "collector": payment_terms.get("collected_by"),
            "currency": payment_terms.get("currency") or currency,
            "net_days": None,
        },
        "fulfillment": {
            "eta": fulfillment_eta,
            "delivery_address": None,
            "contact": None,
        },
        "metadata": {
            "budget_hold_id": budget_hold_id,
            "beckn_confirm_ref": order_id,
        },
    }
