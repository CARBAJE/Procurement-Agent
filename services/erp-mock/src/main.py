"""Mock ERP service — emulates SAP OData v4 + Oracle ERP Cloud REST + a budget
endpoint so the full integration loop can run locally without real tenants.

Routes:
  GET  /health                                                # readiness
  POST /mock/budget/check                                     # adapter's MockERPAdapter target
  POST /sap/oauth2/token
  GET  /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder
  POST /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder
  POST /oauth2/v1/token                                        # Oracle
  POST /fscmRestApi/resources/11.13.18.05/purchaseOrders       # Oracle
"""
from __future__ import annotations

import logging
import os
import sys

# Make sibling modules importable when launched as `python src/main.py`
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp import web

import budget_routes
import oracle_routes
import po_routes
import sap_routes
from config import from_env

logger = logging.getLogger(__name__)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    cfg = from_env()
    app = web.Application()
    app["cfg"] = cfg
    app.router.add_get("/health", health)
    budget_routes.register(app)
    po_routes.register(app)
    sap_routes.register(app)
    oracle_routes.register(app)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
    cfg = from_env()
    logger.info("mock-erp starting scenario=%s port=%d", cfg.scenario, cfg.port)
    web.run_app(create_app(), host="0.0.0.0", port=cfg.port)
