"""Prometheus metric definitions exposed on /metrics.

Per the plan §Observability — names are stable; histogram buckets are tuned
for the budget-check critical path (P95 ≤ 800ms target).
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

budget_check_total = Counter(
    "erp_budget_check_total",
    "Outcome counter for /api/v1/budget/check",
    labelnames=("vendor", "outcome"),
    registry=REGISTRY,
)

budget_check_duration_seconds = Histogram(
    "erp_budget_check_duration_seconds",
    "End-to-end /api/v1/budget/check latency",
    labelnames=("vendor",),
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.5),
    registry=REGISTRY,
)

po_sync_total = Counter(
    "erp_po_sync_total",
    "Vendor push outcomes",
    labelnames=("vendor", "outcome"),
    registry=REGISTRY,
)

po_sync_duration_seconds = Histogram(
    "erp_po_sync_duration_seconds",
    "Latency of a single vendor PO push attempt",
    labelnames=("vendor",),
    buckets=(0.5, 1, 2, 5, 10, 30),
    registry=REGISTRY,
)

po_outbox_lag_seconds = Gauge(
    "erp_po_outbox_lag_seconds",
    "Age of the oldest pending po_push row in seconds",
    registry=REGISTRY,
)

po_outbox_dead_total = Counter(
    "erp_po_outbox_dead_total",
    "Rows that hit MAX_ATTEMPTS without success",
    registry=REGISTRY,
)

webhook_received_total = Counter(
    "erp_webhook_received_total",
    "Inbound webhook outcomes (ok | 401 | 400)",
    labelnames=("vendor", "outcome"),
    registry=REGISTRY,
)

circuit_state = Gauge(
    "erp_circuit_state",
    "Per-vendor circuit breaker state (0=closed, 1=half-open, 2=open)",
    labelnames=("vendor",),
    registry=REGISTRY,
)

token_refresh_total = Counter(
    "erp_token_refresh_total",
    "OAuth token refresh outcomes",
    labelnames=("vendor", "outcome"),
    registry=REGISTRY,
)


def render() -> bytes:
    return generate_latest(REGISTRY)
