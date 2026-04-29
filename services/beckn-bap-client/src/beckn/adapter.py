"""Beckn Protocol v2 adapter.

Routes all calls through the beckn-onix Go adapter (port 8081), which handles:
  - ED25519 request signing
  - Schema validation against official Beckn v2 JSON schemas
  - Asynchronous callback routing for select/init/confirm/status

The Python agent layer only speaks to the ONIX adapter's HTTP API.
It never touches the Beckn network directly.

Architecture:
    Python Agent
        │  HTTP to localhost:8081
        ▼
    beckn-onix Adapter (Go)
        │  Beckn-signed messages
        ▼
    Beckn/ONDC Network (BPPs)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from ..config import BecknConfig
from .models import (
    BecknContext,
    BecknIntent,
    DiscoverRequest,
    SelectMessage,
    SelectOrder,
    SelectRequest,
    SelectedItem,
)


class BecknProtocolAdapter:
    def __init__(self, config: BecknConfig) -> None:
        self.config = config

    # ── Context builder ───────────────────────────────────────────────────────

    def build_context(
        self,
        action: str,
        *,
        transaction_id: str | None = None,
        bpp_id: str | None = None,
        bpp_uri: str | None = None,
    ) -> BecknContext:
        return BecknContext(
            domain=self.config.domain,
            action=action,
            country=self.config.country,
            city=self.config.city,
            core_version=self.config.core_version,
            bap_id=self.config.bap_id,
            bap_uri=self.config.bap_uri,
            transaction_id=transaction_id or str(uuid4()),
            message_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )

    def _wire_context(
        self,
        action: str,
        *,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        message_id: str | None = None,
    ) -> dict:
        """Build camelCase Beckn v2 context dict for wire payloads."""
        return {
            "networkId": self.config.domain,
            "action": action,
            "version": self.config.core_version,
            "bapId": self.config.bap_id,
            "bapUri": self.config.bap_uri,
            "bppId": bpp_id,
            "bppUri": bpp_uri,
            "transactionId": transaction_id,
            "messageId": message_id or str(uuid4()),
            "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            "ttl": "PT30S",
        }

    # ── Shared contract builders ───────────────────────────────────────────────

    def _build_commitments(
        self,
        items: list[SelectedItem],
    ) -> tuple[list[dict], list[dict], list[str]]:
        """Build commitments, considerations, and commitment_ids from item list.

        Shared across /select, /init, /confirm, /status — the Beckn v2.1
        Contract schema requires commitments on every message that carries a
        Contract (including /status via allOf inheritance).

        Returns (commitments, considerations, commitment_ids).
        commitment_ids is passed to _performance_dict for Performance entries.
        """
        commitments: list[dict] = []
        considerations: list[dict] = []
        commitment_ids: list[str] = []

        for i, item in enumerate(items):
            resource_id = f"resource-{item.id}"
            commitment_id = f"commitment-{i + 1:03d}"
            offer_id = f"offer-{i + 1:03d}"
            commitment_ids.append(commitment_id)

            commitments.append({
                "id": commitment_id,
                "descriptor": {
                    "name": item.name or item.id,
                    "code": item.id,
                },
                "status": {"code": "DRAFT"},
                "resources": [{
                    "id": resource_id,
                    "descriptor": {
                        "name": item.name or item.id,
                        "code": item.id,
                    },
                    "quantity": {
                        "unitQuantity": item.quantity,
                        "unitCode": "UNIT",
                    },
                }],
                "offer": {
                    "id": offer_id,
                    "resourceIds": [resource_id],
                },
            })

            if item.price_value:
                total = str(round(float(item.price_value) * item.quantity, 2))
                considerations.append({
                    "id": f"consideration-{i + 1:03d}",
                    "price": {
                        "currency": item.price_currency,
                        "value": total,
                    },
                    "status": {"code": "DRAFT"},
                })

        return commitments, considerations, commitment_ids

    def _performance_dict(self, commitment_ids: list[str]) -> dict:
        """Minimal performance entry referencing commitment_ids.

        performanceAttributes is intentionally omitted — it would require a
        resolvable JSON-LD @context URI which the sandbox does not host.
        Omitting it bypasses the ONIX validator's extended schema check.
        TODO(beckn-v2.1-context): reinstate when a resolvable context exists.
        """
        return {
            "id": f"performance-{uuid4().hex[:8]}",
            "status": {"code": "PENDING"},
            "commitmentIds": commitment_ids,
        }

    def _settlement_dict(self, payment: dict) -> dict:
        """Convert snake_case payment dict → camelCase Beckn settlement entry."""
        out: dict = {
            "id": f"settlement-{uuid4().hex[:8]}",
            "type": payment.get("type", "ON_FULFILLMENT"),
            "collectedBy": payment.get("collected_by", "BPP"),
            "currency": payment.get("currency", "INR"),
            "status": payment.get("status", "NOT-PAID"),
        }
        if payment.get("uri"):
            out["uri"] = payment["uri"]
        if payment.get("transaction_id"):
            out["transactionId"] = payment["transaction_id"]
        return out

    # ── Request builders ──────────────────────────────────────────────────────

    def build_discover_request(
        self,
        intent: BecknIntent,
        transaction_id: str | None = None,
    ) -> DiscoverRequest:
        """Build a v2 discover request.

        Discovery is synchronous in v2 — the ONIX adapter queries the
        Catalog Service and returns matching offerings directly.
        """
        context = self.build_context("discover", transaction_id=transaction_id)
        return DiscoverRequest(context=context, message=intent)

    def build_select_request(
        self,
        order: SelectOrder,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> SelectRequest:
        context = self.build_context(
            "select",
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )
        return SelectRequest(context=context, message=SelectMessage(order=order))

    def build_select_wire_payload(
        self,
        order: SelectOrder,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /select payload in real Beckn v2 camelCase wire format.

        Beckn v2.0.0 changed the select message from {order} to {contract}.
        The contract groups selected resources, participants, and pricing.
        """
        context = self._wire_context("select", transaction_id=transaction_id, bpp_id=bpp_id, bpp_uri=bpp_uri)
        contract_id = str(uuid4())
        commitments, considerations, _ = self._build_commitments(order.items)

        contract: dict = {
            "id": contract_id,
            "participants": [{
                "id": self.config.bap_id,
                "descriptor": {"name": self.config.bap_id, "code": "buyer"},
            }],
            "commitments": commitments,
        }
        if considerations:
            contract["consideration"] = considerations

        return {"context": context, "message": {"contract": contract}}

    def build_discover_wire_payload(
        self,
        intent: BecknIntent,
        transaction_id: str | None = None,
    ) -> tuple[dict, str]:
        """Build /discover payload in real Beckn v2 camelCase wire format.

        Returns (payload_dict, transaction_id).
        Used by discover_async() when talking to a real ONIX adapter.
        """
        txn_id = transaction_id or str(uuid4())
        context = {
            "networkId": self.config.domain,
            "action": "discover",
            "version": self.config.core_version,
            "bapId": self.config.bap_id,
            "bapUri": self.config.bap_uri,
            "transactionId": txn_id,
            "messageId": str(uuid4()),
            "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            "ttl": "PT30S",
        }
        # Real Beckn v2 Intent schema: {textSearch, filters, spatial, mediaSearch}
        # additionalProperties: false — item/fulfillment/payment are NOT supported
        search_terms = [intent.item] + intent.descriptions
        intent_obj: dict = {"textSearch": " ".join(search_terms)}

        payload = {"context": context, "message": {"intent": intent_obj}}
        return payload, txn_id

    def build_init_wire_payload(
        self,
        contract_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /init payload in Beckn v2.1 Contract shape.

        Extends the /select contract with a buyer Participant (billing) and a
        Performance entry (fulfillment). Uses hardcoded mock buyer info — swap
        for a real BillingProvider when buyer identity management lands.
        """
        context = self._wire_context("init", transaction_id=transaction_id, bpp_id=bpp_id, bpp_uri=bpp_uri)
        commitments, considerations, commitment_ids = self._build_commitments(items)

        buyer_participant = {
            "id": self.config.bap_id,
            "descriptor": {"code": "buyer", "name": "Procurement Agent"},
            "contact": {
                "name": "Procurement Agent",
                "email": "procurement@example.com",
                "phone": "+91-0000000000",
            },
        }

        contract: dict = {
            "id": contract_id,
            "participants": [buyer_participant],
            "commitments": commitments,
            "performance": [self._performance_dict(commitment_ids)],
        }
        if considerations:
            contract["consideration"] = considerations

        return {"context": context, "message": {"contract": contract}}

    def build_confirm_wire_payload(
        self,
        contract_id: str,
        items: list[SelectedItem],
        payment: dict,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /confirm payload in Beckn v2.1 Contract shape.

        Moves payment into a Settlement entry and marks contract ACTIVE.
        Commitments are re-included because Contract schema requires them on
        every message (Beckn v2.1 allOf inheritance).

        Contract.status.code enum: DRAFT | ACTIVE | CANCELLED | COMPLETE.
        Must be "ACTIVE" here — "CONFIRMED" is not a valid enum value.
        """
        context = self._wire_context("confirm", transaction_id=transaction_id, bpp_id=bpp_id, bpp_uri=bpp_uri)
        commitments, considerations, _ = self._build_commitments(items)

        contract: dict = {
            "id": contract_id,
            "commitments": commitments,
            "settlements": [self._settlement_dict(payment)],
            "status": {"code": "ACTIVE"},
        }
        if considerations:
            contract["consideration"] = considerations

        return {"context": context, "message": {"contract": contract}}

    def build_status_wire_payload(
        self,
        order_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /status payload in Beckn v2.1 shape.

        /status inherits Contract via allOf, so commitments are required even
        though semantically this is just a "query by id" call. Items are
        replayed from session state on every poll.
        """
        context = self._wire_context("status", transaction_id=transaction_id, bpp_id=bpp_id, bpp_uri=bpp_uri)
        commitments, _, _ = self._build_commitments(items)

        return {
            "context": context,
            "message": {"contract": {"id": order_id, "commitments": commitments}},
        }

    # ── Signing ───────────────────────────────────────────────────────────────

    def sign_request(self, payload: dict) -> dict:
        """Pass-through: ED25519 signing is handled by the beckn-onix adapter.

        In production, the ONIX adapter's signer.so plugin attaches the
        Authorization header automatically. This method exists as a hook
        for local testing without the ONIX adapter.
        """
        return payload

    # ── URL routing ───────────────────────────────────────────────────────────

    @property
    def discover_url(self) -> str:
        """ONIX adapter discovery endpoint — BAP caller path, async on_discover callback."""
        return f"{self.config.onix_url.rstrip('/')}/bap/caller/discover"

    @property
    def select_url(self) -> str:
        """ONIX adapter select endpoint — ONIX routes to BPP /receiver/select."""
        return f"{self.config.onix_url.rstrip('/')}/bap/caller/select"

    def caller_action_url(self, action: str) -> str:
        """Generic ONIX adapter caller endpoint for init/confirm/status."""
        return f"{self.config.onix_url.rstrip('/')}/bap/caller/{action}"
