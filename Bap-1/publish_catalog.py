"""
publish_catalog.py — Publish A4 paper catalog to the Beckn testnet via onix-bpp.

Run ONCE (after docker compose up) before running run.py:
    python publish_catalog.py

This registers our 3 paper suppliers in the Beckn Catalog Service so that
discover requests from the BAP can find them.

Requires onix-bpp running on port 8082:
    cd starter-kit/generic-devkit/install
    docker compose -f docker-compose-generic-local.yml up -d
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

ONIX_BPP_URL = "http://localhost:8082/bpp/caller/publish"
BPP_ID = "bpp.example.com"
BPP_URI = "http://onix-bpp:8082/bpp/receiver"
BAP_ID = "bap.example.com"
BAP_URI = "http://host.docker.internal:8000/bap/receiver"

# ── A4 paper catalog — 3 suppliers ───────────────────────────────────────────

CATALOG = {
    "id": "CAT-PROCUREMENT-A4-001",
    "descriptor": {
        "name": "Office Stationery Procurement Catalog",
        "shortDesc": "A4 paper and stationery supplies for procurement",
    },
    "provider": {
        "id": "PROV-OFFICEWORLD-01",
        "descriptor": {"name": "OfficeWorld Supplies"},
        "availableAt": [
            {
                "geo": {"type": "Point", "coordinates": [77.5946, 12.9716]},
                "address": {
                    "streetAddress": "14 MG Road",
                    "addressLocality": "Bengaluru",
                    "addressRegion": "Karnataka",
                    "postalCode": "560001",
                    "addressCountry": "IN",
                },
            }
        ],
    },
    "resources": [
        {
            "id": "item-a4-80gsm",
            "descriptor": {
                "name": "A4 Paper 80gsm (500 sheets)",
                "shortDesc": "A4 paper 80gsm ream 500 sheets",
                "longDesc": (
                    "Premium quality A4 size paper, 80gsm weight, 500 sheets per ream. "
                    "Suitable for laser and inkjet printers. "
                    "White, high brightness, acid-free."
                ),
            },
            "provider": {
                "id": "PROV-OFFICEWORLD-01",
                "descriptor": {"name": "OfficeWorld Supplies"},
            },
            "price": {"currency": "INR", "value": "195.00"},
            "rating": {
                "ratingValue": 4.8,
                "ratingCount": 1200,
                "bestRating": 5,
                "worstRating": 1,
            },
            "availableAt": [
                {
                    "geo": {"type": "Point", "coordinates": [77.5946, 12.9716]},
                    "address": {"addressLocality": "Bengaluru", "addressCountry": "IN"},
                }
            ],
        },
        {
            "id": "item-a4-ream",
            "descriptor": {
                "name": "A4 Paper 80gsm Ream",
                "shortDesc": "A4 80gsm ream 500 sheets",
                "longDesc": (
                    "Standard A4 paper ream, 80gsm, 500 sheets. "
                    "Ideal for everyday printing and photocopying."
                ),
            },
            "provider": {
                "id": "PROV-PAPERDIRECT-01",
                "descriptor": {"name": "PaperDirect India"},
            },
            "price": {"currency": "INR", "value": "189.00"},
            "rating": {
                "ratingValue": 4.5,
                "ratingCount": 850,
                "bestRating": 5,
                "worstRating": 1,
            },
            "availableAt": [
                {
                    "geo": {"type": "Point", "coordinates": [77.5946, 12.9716]},
                    "address": {"addressLocality": "Bengaluru", "addressCountry": "IN"},
                }
            ],
        },
        {
            "id": "item-a4-premium",
            "descriptor": {
                "name": "A4 Paper Premium 80gsm",
                "shortDesc": "Premium A4 paper 80gsm high brightness",
                "longDesc": (
                    "Premium A4 paper 80gsm, 500 sheets per ream. "
                    "High brightness (104%) for crisp, vibrant prints. "
                    "Compatible with all printers."
                ),
            },
            "provider": {
                "id": "PROV-STATHUB-01",
                "descriptor": {"name": "Stationery Hub"},
            },
            "price": {"currency": "INR", "value": "201.00"},
            "rating": {
                "ratingValue": 4.9,
                "ratingCount": 2300,
                "bestRating": 5,
                "worstRating": 1,
            },
            "availableAt": [
                {
                    "geo": {"type": "Point", "coordinates": [77.5946, 12.9716]},
                    "address": {"addressLocality": "Bengaluru", "addressCountry": "IN"},
                }
            ],
        },
    ],
    "offers": [
        {
            "id": "OFFER-A4-BULK-001",
            "descriptor": {
                "name": "A4 Paper Bulk Supply",
                "shortDesc": "Office stationery — A4 paper from multiple suppliers",
            },
            "resourceIds": ["item-a4-80gsm", "item-a4-ream", "item-a4-premium"],
            "provider": {
                "id": "PROV-OFFICEWORLD-01",
                "descriptor": {"name": "OfficeWorld Supplies"},
            },
            "validity": {
                "startDate": "2026-01-01T00:00:00Z",
                "endDate": "2026-12-31T23:59:59Z",
            },
        }
    ],
    "publishDirectives": {"catalogType": "regular"},
}


async def publish() -> None:
    payload = {
        "context": {
            "networkId": "beckn.one/testnet",
            "action": "catalog/publish",
            "version": "2.0.0",
            "bapId": BAP_ID,
            "bapUri": BAP_URI,
            "bppId": BPP_ID,
            "bppUri": BPP_URI,
            "transactionId": str(uuid4()),
            "messageId": str(uuid4()),
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "ttl": "PT30S",
        },
        "message": {"catalogs": [CATALOG]},
    }

    log.info("Publishing A4 paper catalog to %s ...", ONIX_BPP_URL)
    log.info("  Catalog ID : %s", CATALOG["id"])
    log.info("  Resources  : %d items", len(CATALOG["resources"]))
    for r in CATALOG["resources"]:
        log.info(
            "    [%s] %s — Rs. %s",
            r["id"],
            r["descriptor"]["name"],
            r.get("price", {}).get("value", "N/A"),
        )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            ONIX_BPP_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as resp:
            body = await resp.json()
            if resp.status == 200:
                # Response structure varies by Catalog Service implementation
                ack = (
                    body.get("message", {}).get("ack", {}).get("status")
                    or body.get("ack", {}).get("status")
                    or body.get("status")
                    or "OK"
                )
                log.info("Catalog published | HTTP=200 | status=%s", ack)
                print("\n  Catalog published successfully.")
                print("  You can now run: python run.py\n")
            else:
                err = body.get("message", {}).get("error", body)
                log.error("Publish failed (HTTP %d): %s", resp.status, err)


if __name__ == "__main__":
    asyncio.run(publish())
