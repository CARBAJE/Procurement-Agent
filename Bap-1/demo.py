"""
BAP Demo -- self-contained, no external services needed.

Simulates the full Beckn flow in-process:
  1. BAP sends /search  (mocked HTTP call to a fake gateway)
  2. Three mock BPPs respond asynchronously via /on_search callbacks
  3. BAP collects responses, picks the best offer
  4. BAP sends /select to the chosen BPP  (mocked HTTP call)

Run:
    python demo.py
"""
import asyncio
import json

from aioresponses import aioresponses

from src.beckn.callbacks import OnSearchCollector
from src.beckn.client import BecknClient
from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.models import (
    Descriptor,
    Fulfillment,
    FulfillmentEnd,
    GPSLocation,
    ItemQuantity,
    Payment,
    PaymentParams,
    SearchIntent,
    SearchItem,
    SelectOrder,
    SelectProvider,
    SelectedItem,
    TimeConstraint,
)
from src.config import BecknConfig

# ── Mock BPP responses ────────────────────────────────────────────────────────

SELLERS = [
    {
        "id": "seller-1",
        "name": "OfficeWorld Supplies",
        "bpp_uri": "https://officeworld.example.com/beckn",
        "price": "195.00",
        "rating": "4.8",
        "item_id": "item-a4-80gsm-500pk",
        "delivery_days": 2,
    },
    {
        "id": "seller-2",
        "name": "PaperDirect India",
        "bpp_uri": "https://paperdirect.example.com/beckn",
        "price": "189.00",
        "rating": "4.5",
        "item_id": "item-a4-paper-ream",
        "delivery_days": 3,
    },
    {
        "id": "seller-3",
        "name": "Stationery Hub",
        "bpp_uri": "https://stathub.example.com/beckn",
        "price": "201.00",
        "rating": "4.9",
        "item_id": "item-a4-premium",
        "delivery_days": 1,
    },
]


def make_on_search_payload(txn_id: str, seller: dict) -> dict:
    return {
        "context": {
            "domain": "nic2004:52110",
            "action": "on_search",
            "country": "IND",
            "city": "std:080",
            "core_version": "1.1.0",
            "bap_id": "procurement-bap",
            "bap_uri": "http://localhost:8000/beckn",
            "bpp_id": seller["id"],
            "bpp_uri": seller["bpp_uri"],
            "transaction_id": txn_id,
            "message_id": f"msg-{seller['id']}",
            "timestamp": "2024-01-01T00:00:00.000Z",
        },
        "message": {
            "catalog": {
                "bpp/descriptor": {"name": seller["name"]},
                "bpp/providers": [
                    {
                        "id": f"prov-{seller['id']}",
                        "descriptor": {"name": seller["name"]},
                        "rating": seller["rating"],
                        "items": [
                            {
                                "id": seller["item_id"],
                                "descriptor": {"name": "A4 paper 80gsm (500 sheets)"},
                                "price": {
                                    "currency": "INR",
                                    "value": seller["price"],
                                },
                                "quantity": {"count": 500},
                            }
                        ],
                    }
                ],
            }
        },
    }


# ── Simulation helpers ────────────────────────────────────────────────────────


async def simulate_bpp_callbacks(
    collector: OnSearchCollector, txn_id: str
) -> None:
    """Simulates BPPs asynchronously calling back /on_search after search."""
    delays = [0.3, 0.6, 1.0]  # BPPs respond at different times
    for seller, delay in zip(SELLERS, delays):
        await asyncio.sleep(delay)
        await collector.handle_callback(make_on_search_payload(txn_id, seller))
        print(f"  [BPP callback] {seller['name']} responded -- Rs. {seller['price']}/ream")


def pick_best_offer(responses) -> tuple:
    """Pick the seller with the lowest price among on_search responses."""
    best = None
    best_price = float("inf")
    for resp in responses:
        provider = resp.message.catalog.bpp_providers[0]
        price = float(provider.items[0].price.value)
        if price < best_price:
            best_price = price
            best = (resp, provider)
    return best


# ── Main demo ─────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("  BAP Demo -- Agentic Procurement on Beckn Protocol")
    print("=" * 60)

    # Config & components
    config = BecknConfig(
        bap_id="procurement-bap",
        bap_uri="http://localhost:8000/beckn",
        gateway_url="https://sandbox.becknprotocol.io",
    )
    adapter = BecknProtocolAdapter(config)
    collector = OnSearchCollector(default_timeout=5.0)

    # What the agent wants to buy
    intent = SearchIntent(
        item=SearchItem(
            descriptor=Descriptor(name="A4 paper 80gsm"),
            quantity=ItemQuantity(count=500),
        ),
        fulfillment=Fulfillment(
            end=FulfillmentEnd(
                location=GPSLocation(gps="12.9716,77.5946"),
                time=TimeConstraint(duration="P3D"),
            )
        ),
        payment=Payment(params=PaymentParams(amount="100000", currency="INR")),
    )

    print("\n[Step 1] Procurement request")
    print(f"  Item   : {intent.item.descriptor.name}")
    print(f"  Qty    : {intent.item.quantity.count} reams")
    print(f"  Budget : Rs. 1,00,000")
    print(f"  Deliver: Bangalore (GPS 12.9716,77.5946) within 3 days")

    ACK = {"message": {"ack": {"status": "ACK"}}}

    with aioresponses() as mock:
        # Mock gateway /search and all BPP /select endpoints
        mock.post("https://sandbox.becknprotocol.io/search", payload=ACK)
        for s in SELLERS:
            mock.post(f"{s['bpp_uri']}/select", payload=ACK)

        async with BecknClient(adapter) as client:

            # ── Step 2: /search ───────────────────────────────────────────────
            print("\n[Step 2] Broadcasting /search to Beckn network...")
            txn_id, _ = await client.search(intent)
            print(f"  Transaction ID : {txn_id}")
            print(f"  Gateway        : {adapter.gateway_search_url}")

            # ── Step 3: /on_search (async callbacks) ──────────────────────────
            print("\n[Step 3] Waiting for seller responses (/on_search)...")
            collector.register(txn_id)

            # Simulate BPPs responding in the background
            callback_task = asyncio.create_task(
                simulate_bpp_callbacks(collector, txn_id)
            )

            # Collect all responses (waits up to 5s)
            responses = await collector.collect(txn_id, timeout=2.0)
            await callback_task

            print(f"\n  {len(responses)} seller(s) responded:")
            for resp in responses:
                prov = resp.message.catalog.bpp_providers[0]
                item = prov.items[0]
                print(
                    f"    - {prov.descriptor.name:30s} "
                    f"Rs. {item.price.value}/ream  "
                    f"*{prov.rating}"
                )

            # ── Step 4: Pick best offer ───────────────────────────────────────
            print("\n[Step 4] Comparing offers (lowest price)...")
            result = pick_best_offer(responses)
            if not result:
                print("  No offers received. Exiting.")
                return

            chosen_resp, chosen_provider = result
            chosen_item = chosen_provider.items[0]
            print(
                f"  Selected : {chosen_provider.descriptor.name}\n"
                f"  Price    : Rs. {chosen_item.price.value}/ream\n"
                f"  Rating   : *{chosen_provider.rating}\n"
                f"  BPP URI  : {chosen_resp.context.bpp_uri}"
            )

            # ── Step 5: /select ───────────────────────────────────────────────
            print("\n[Step 5] Sending /select to chosen seller...")
            order = SelectOrder(
                provider=SelectProvider(id=chosen_provider.id),
                items=[
                    SelectedItem(
                        id=chosen_item.id,
                        quantity=ItemQuantity(count=500),
                    )
                ],
            )
            select_ack = await client.select(
                order,
                transaction_id=txn_id,
                bpp_id=chosen_resp.context.bpp_id,
                bpp_uri=chosen_resp.context.bpp_uri,
            )
            status = select_ack["message"]["ack"]["status"]
            print(f"  /select ACK : {status}")

    collector.cleanup(txn_id)

    print("\n" + "=" * 60)
    print("  Flow complete.")
    print(f"  Next: /init -> /confirm -> /status  (Phase 2)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
