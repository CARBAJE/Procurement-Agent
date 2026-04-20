"""
Real BAP runner — Beckn Protocol v2 — Procurement ReAct Agent.

Requires:
  - Docker stack running (onix-bap, onix-bpp, sandbox-bpp, redis)
      cd starter-kit/generic-devkit/install
      docker compose -f docker-compose-my-bap.yml up -d
  - Ollama running with qwen3:1.7b (for NL query mode)
      ollama run qwen3:1.7b
  - .env configured (see .env.example)

Run:
    python run.py                                       # hardcoded intent
    python run.py "500 reams A4 paper Bangalore"        # NL query (Ollama)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from aiohttp import web

from src.agent import ProcurementAgent
from src.beckn.adapter import BecknProtocolAdapter
from src.beckn.models import BecknIntent, BudgetConstraints
from src.config import BecknConfig
from src.server import collector, create_app

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

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
    config = BecknConfig()
    adapter = BecknProtocolAdapter(config)
    nl_query = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n" + "=" * 60)
    print("  Procurement ReAct Agent — Beckn Protocol v2")
    print("=" * 60)
    print(f"  BAP ID   : {config.bap_id}")
    print(f"  ONIX URL : {config.onix_url}")
    print(f"  Mode     : {'NL query' if nl_query else 'hardcoded intent'}")

    runner = await start_server(port=8000)

    try:
        agent = ProcurementAgent(
            adapter=adapter,
            collector=collector,
            discover_timeout=config.callback_timeout,
        )

        print("\n  Running agent...\n")

        if nl_query:
            result = await agent.arun(nl_query)
        else:
            sys.exit("No NL query provided. Please run with a query argument, e.g.:\n  python run.py \"500 reams A4 paper Bangalore\"")

        print("  Reasoning trace:")
        for msg in result["messages"]:
            print(f"    {msg}")

        if result.get("error"):
            print(f"\n  ERROR: {result['error']}")
            sys.exit(1)

        print("\n  Done. Next: /init -> /confirm -> /status")
        print("=" * 60 + "\n")

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
