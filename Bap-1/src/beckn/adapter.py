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
    BillingInfo,
    DiscoverRequest,
    FulfillmentInfo,
    PaymentTerms,
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
        context = {
            "networkId": self.config.domain,
            "action": "select",
            "version": self.config.core_version,
            "bapId": self.config.bap_id,
            "bapUri": self.config.bap_uri,
            "bppId": bpp_id,
            "bppUri": bpp_uri,
            "transactionId": transaction_id,
            "messageId": str(uuid4()),
            "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            "ttl": "PT30S",
        }

        contract_id = str(uuid4())
        commitments = []
        considerations = []

        for i, item in enumerate(order.items):
            resource_id = f"resource-{item.id}"
            commitment_id = f"commitment-{i + 1:03d}"
            offer_id = f"offer-{i + 1:03d}"

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

    # ── /init, /confirm, /status (Phase 2 — full transaction lifecycle) ──────
    # Reference: KnowledgeBase/project_scaffold/components/beckn_bap_client.md
    #            + phase2_core_intelligence_transaction_flow.md
    #
    # The validator is Beckn v2.1 (Contract model with additionalProperties: false).
    # Buyer billing info → contract.participants[role=buyer].
    # Fulfillment       → contract.performance[{id, status, commitmentIds,
    #                     performanceAttributes: {...actual delivery data...}}].
    # Payment           → contract.settlements[].
    # /status           → {message: {contract: {id}}} (not {orderId: ...}).

    def _wire_context(
        self,
        action: str,
        *,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
        message_id: str | None = None,
    ) -> dict:
        """Shared camelCase context builder for init/confirm/status payloads."""
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

    @staticmethod
    def _address_dict(address) -> dict:
        """Address Pydantic model → Beckn v2 wire dict (camelCase, drop None)."""
        raw = {
            "door": address.door,
            "building": address.building,
            "street": address.street,
            "city": address.city,
            "state": address.state,
            "country": address.country,
            "areaCode": address.area_code,
        }
        return {k: v for k, v in raw.items() if v is not None}

    def _buyer_participant_dict(self, billing: BillingInfo) -> dict:
        """Buyer billing info → a Participant entry with role code 'buyer'.

        Participants[] is permissive (no additionalProperties: false), so we
        attach contact + address + taxId at the top level. A future stricter
        schema version would likely nest them under participantAttributes.
        """
        out: dict = {
            "id": self.config.bap_id,
            "descriptor": {"code": "buyer", "name": billing.name},
            "contact": {
                "name": billing.name,
                "email": billing.email,
                "phone": billing.phone,
            },
            "address": self._address_dict(billing.address),
        }
        if billing.tax_id:
            out["taxId"] = billing.tax_id
        return out

    def _performance_dict(
        self,
        fulfillment: FulfillmentInfo,
        commitment_ids: list[str],
    ) -> dict:
        """Fulfillment → a Performance entry (minimal envelope).

        Performance allows {id, status, commitmentIds, performanceAttributes}.
        None of these are required, so we omit performanceAttributes to avoid
        triggering JSON-LD Extended Schema validation (which would try to
        dereference the @context URI as a schema — requiring a resolvable
        domain vocabulary that the sandbox doesn't host).

        The `fulfillment` argument is accepted for forward-compat but not
        currently serialized on the wire. When a resolvable Beckn v2.1
        HyperlocalDelivery context is available, reinstate:
            performanceAttributes = {
                "@context": "https://schema.beckn.io/v2.1/HyperlocalDelivery",
                "@type": "Delivery",
                ...concrete delivery fields...
            }
        TODO(beckn-v2.1-context): hook up resolvable context + restore details.
        See: Bap-1/docs/ARCHITECTURE.md §7.1 #1 for the full blocker description,
             live debugging notes, and recommended unblock options.
        """
        _ = fulfillment   # intentionally unused until a resolvable context exists
        return {
            "id": f"performance-{uuid4().hex[:8]}",
            "status": {"code": "PENDING"},
            "commitmentIds": commitment_ids,
        }

    def _settlement_dict(self, payment: PaymentTerms) -> dict:
        """PaymentTerms → a Settlement entry.

        Settlements[] is permissive, so payment fields sit at the top level.
        """
        out: dict = {
            "id": f"settlement-{uuid4().hex[:8]}",
            "type": payment.type,
            "collectedBy": payment.collected_by,
            "currency": payment.currency,
            "status": payment.status,
        }
        if payment.uri:
            out["uri"] = payment.uri
        if payment.transaction_id:
            out["transactionId"] = payment.transaction_id
        return out

    def _build_commitments(self, items: list[SelectedItem]) -> tuple[list[dict], list[dict], list[str]]:
        """Shared between /select, /init, /confirm — build commitments + considerations.

        Returns (commitments, considerations, commitment_ids). The ids are
        exposed so Performance entries can reference them via commitmentIds.
        """
        commitments = []
        considerations = []
        commitment_ids = []
        for i, item in enumerate(items):
            resource_id = f"resource-{item.id}"
            commitment_id = f"commitment-{i + 1:03d}"
            offer_id = f"offer-{i + 1:03d}"
            commitment_ids.append(commitment_id)

            commitments.append({
                "id": commitment_id,
                "descriptor": {"name": item.name or item.id, "code": item.id},
                "status": {"code": "DRAFT"},
                "resources": [{
                    "id": resource_id,
                    "descriptor": {"name": item.name or item.id, "code": item.id},
                    "quantity": {
                        "unitQuantity": item.quantity,
                        "unitCode": "UNIT",
                    },
                }],
                "offer": {"id": offer_id, "resourceIds": [resource_id]},
            })

            if item.price_value:
                total = str(round(float(item.price_value) * item.quantity, 2))
                considerations.append({
                    "id": f"consideration-{i + 1:03d}",
                    "price": {"currency": item.price_currency, "value": total},
                    "status": {"code": "DRAFT"},
                })

        return commitments, considerations, commitment_ids

    def build_init_wire_payload(
        self,
        *,
        contract_id: str,
        items: list[SelectedItem],
        billing: BillingInfo,
        fulfillment: FulfillmentInfo,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /init payload in Beckn v2.1 Contract shape.

        Extends the /select contract with a buyer Participant (billing) and a
        Performance entry (fulfillment). The BPP uses these to draft the final
        invoice and plan the delivery.
        """
        context = self._wire_context(
            "init",
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )
        commitments, considerations, commitment_ids = self._build_commitments(items)

        contract: dict = {
            "id": contract_id,
            "participants": [self._buyer_participant_dict(billing)],
            "commitments": commitments,
            "performance": [self._performance_dict(fulfillment, commitment_ids)],
        }
        if considerations:
            contract["consideration"] = considerations

        return {"context": context, "message": {"contract": contract}}

    def build_confirm_wire_payload(
        self,
        *,
        contract_id: str,
        items: list[SelectedItem],
        payment: PaymentTerms,
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /confirm payload in Beckn v2.1 Contract shape.

        Moves the payment into a Settlement entry and marks the contract status
        as ACTIVE (per Contract.status.code enum: DRAFT|ACTIVE|CANCELLED|COMPLETE).
        Commitments are re-included because the Contract schema requires them.
        """
        context = self._wire_context(
            "confirm",
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )
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
        *,
        order_id: str,
        items: list[SelectedItem],
        transaction_id: str,
        bpp_id: str,
        bpp_uri: str,
    ) -> dict:
        """Build /status payload in Beckn v2.1 shape.

        The action schema is `allOf: [Contract, {required: [id]}]`, i.e. it
        inherits ALL of Contract's required properties — including
        `commitments` (minItems: 1). So even though semantically /status is
        just "query by id", the wire payload needs a full Contract envelope.
        Callers replay the commitments they originally sent in /init.
        """
        context = self._wire_context(
            "status",
            transaction_id=transaction_id,
            bpp_id=bpp_id,
            bpp_uri=bpp_uri,
        )
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
