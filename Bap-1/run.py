"""
Real BAP runner — Beckn Protocol v2.

v2 change: discovery is synchronous.
  No waiting for callbacks during discover — offerings arrive immediately.
  Callbacks still used for on_select, on_init, on_confirm, on_status.

Requires:
  - mock_onix.py running on port 8081  (or real beckn-onix adapter)
  - .env configured (see .env.example)
  - Ollama running (for NL query mode)

Run:
    Terminal 1:  python mock_onix.py
    Terminal 2:  python run.py                          # hardcoded intent
    Terminal 2:  python run.py "500 A4 paper Bangalore" # NL query
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from aiohttp import web

from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.client import BecknClient
from src.beckn.models import (
    BecknIntent,
    BudgetConstraints,
    SelectOrder,
    SelectProvider,
    SelectedItem,
)
from src.config import BecknConfig
from src.server import collector, create_app

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
# Only show warnings/errors from aiohttp internals
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


# ── Procurement intent (edit this) ────────────────────────────────────────────

INTENT = BecknIntent(
    item="A4 paper 80gsm",
    descriptions=["A4", "80gsm"],
    quantity=500,
    location_coordinates="12.9716,77.5946",
    delivery_timeline=72,                        # 3 days in hours
    budget_constraints=BudgetConstraints(max=200.0),
)


# ── Server startup ────────────────────────────────────────────────────────────


async def start_server(port: int = 8000) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner


# ── Main flow ─────────────────────────────────────────────────────────────────


async def main() -> None:
    # Resolve intent: NL query from CLI arg, or hardcoded fallback
    nl_query = sys.argv[1] if len(sys.argv) > 1 else None
    if nl_query:
        from src.nlp.intent_parser_facade import parse_nl_to_intent
        intent = parse_nl_to_intent(nl_query)
        if intent is None:
            print(f"  Query not recognised as procurement: {nl_query!r}")
            sys.exit(1)
    else:
        intent = INTENT

    config = BecknConfig()
    adapter = BecknProtocolAdapter(config)

    print("\n" + "=" * 60)
    print("  Real BAP -- Beckn Protocol v2")
    print("=" * 60)
    print(f"  BAP ID     : {config.bap_id}")
    print(f"  ONIX URL   : {config.onix_url}")
    print(f"  Item       : {intent.item}")
    print(f"  Quantity   : {intent.quantity}")
    print(f"  Timeline   : {intent.delivery_timeline}h")
    if intent.budget_constraints:
        print(f"  Budget max : Rs. {intent.budget_constraints.max}")

    runner = await start_server(port=8000)

    try:
        async with BecknClient(adapter) as client:

            # 1. Async discover — send to ONIX, wait for on_discover callback
            print("\n  Discovering ...")
            discover_resp = await client.discover_async(
                intent, collector, timeout=config.callback_timeout
            )
            txn_id = discover_resp.transaction_id

            if not discover_resp.offerings:
                print("  No offerings returned.")
                return

            # 2. Print all offerings
            print(f"\n  {len(discover_resp.offerings)} offering(s) found:\n")
            for o in discover_resp.offerings:
                print(
                    f"    [{o.bpp_id:20s}]  {o.provider_name:30s}  "
                    f"Rs. {o.price_value:8s}  *{o.rating}"
                )

            # 3. Pick cheapest
            best = min(discover_resp.offerings, key=lambda o: float(o.price_value))
            print(f"\n  Selected : {best.provider_name}")
            print(f"  Price    : Rs. {best.price_value}")
            print(f"  BPP      : {best.bpp_id}")

            # 4. Register on_select callback, then send /select
            print(f"\n  Selecting {best.provider_name} ...")
            collector.register(txn_id, "on_select")
            order = SelectOrder(
                provider=SelectProvider(id=best.provider_id),
                items=[SelectedItem(
                    id=best.item_id,
                    quantity=intent.quantity,
                    name=best.item_name,
                    price_value=best.price_value,
                    price_currency=best.price_currency,
                )],
            )
            select_ack = await client.select(
                order,
                transaction_id=txn_id,
                bpp_id=best.bpp_id,
                bpp_uri=best.bpp_uri,
            )

            # 5. Wait for on_select callback
            callbacks = await collector.collect(txn_id, "on_select", timeout=5.0)
            if callbacks:
                state = (
                    callbacks[0].message.get("order", {}).get("state")
                    or callbacks[0].message.get("contract", {}).get("status", {}).get("code")
                    or "RECEIVED"
                )
                print(f"  on_select: {state}")
            else:
                print("  on_select: no callback received within timeout")

            collector.cleanup(txn_id, "on_select")

        print("\n  Done. Next: /init -> /confirm -> /status")
        print("=" * 60 + "\n")

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
