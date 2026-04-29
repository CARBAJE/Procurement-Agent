"""PaymentProvider — swappable source for payment terms in /confirm."""
from __future__ import annotations

from typing import Optional, Protocol

from ...config import BecknConfig
from ..models import PaymentTerms, PaymentType


class PaymentProvider(Protocol):
    """Proposes payment terms to the BPP in /confirm.

    The BPP may accept, counter, or reject these in on_init; the final terms
    come back via InitResponse.payment_terms. Providers are only asked for an
    opening proposal, not a running negotiation.
    """

    def propose_terms(
        self,
        *,
        total_value: Optional[str] = None,
        currency: str = "INR",
        user_id: Optional[str] = None,
    ) -> PaymentTerms: ...


class CODPaymentProvider:
    """Phase 2: Cash / Pay On Delivery — the sandbox-safe default.

    No payment gateway integration required — the BPP collects at the point
    of fulfillment. This is the most common sandbox setup and satisfies
    "complete order lifecycle" without stubbing UPI/Razorpay.

    TO SWAP FOR REAL:
      - UPIPaymentProvider: populate `uri` with a UPI deep-link and set
        type=ON_ORDER, collected_by=BAP.
      - RazorpayPaymentProvider: create a payment order server-side and
        populate `uri` + `transaction_id`.
      One line change in providers/__init__.py build_providers().
    """

    def __init__(
        self,
        payment_type: PaymentType = "ON_FULFILLMENT",
        collected_by: str = "BPP",
    ) -> None:
        self._type = payment_type
        self._collected_by = collected_by

    def propose_terms(
        self,
        *,
        total_value: Optional[str] = None,
        currency: str = "INR",
        user_id: Optional[str] = None,
    ) -> PaymentTerms:
        return PaymentTerms(
            type=self._type,
            collected_by=self._collected_by,
            currency=currency,
            status="NOT-PAID",
        )


def build_cod_provider(config: BecknConfig) -> CODPaymentProvider:
    """Helper — build the COD provider honouring config overrides."""
    # Narrow str → Literal for the type checker; config validation keeps
    # only the 3 supported values at runtime.
    payment_type: PaymentType = (
        config.default_payment_type
        if config.default_payment_type
        in ("ON_ORDER", "ON_FULFILLMENT", "POST_FULFILLMENT")
        else "ON_FULFILLMENT"
    )  # type: ignore[assignment]
    return CODPaymentProvider(
        payment_type=payment_type,
        collected_by=config.default_payment_collector or "BPP",
    )
