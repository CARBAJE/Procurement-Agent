"""Result aggregation + deduplication.

Implements Subagent 3's spec: take the heterogeneous list of
:class:`NetworkResult` objects returned by the resilience layer, merge
duplicates that represent the same physical offering on multiple
networks, and emit a single canonical catalog of :class:`AggregatedItem`.

Deduplication strategy
======================

A two-stage match:

1. **Primary signature** ``(normalized_tax_id, normalized_name, currency)``.
   Two items with the same tax-registered supplier and the same item
   name are considered the same offering even if the per-network
   ``provider_id`` differs.

2. **Geographic refinement** within a primary group: when two items
   share the (name, currency) but have different (or missing) tax-IDs,
   they merge only if their advertised GPS coordinates are within
   :data:`DEFAULT_GEO_PROXIMITY_KM` (great-circle distance via the
   Haversine formula).

Merge resolution
================

Within a duplicate cluster, the *canonical* item is chosen by:

1. Lowest ``price`` (the buyer wins).
2. Tie-break: highest ``quantity_available`` (richest record).
3. Tie-break: shortest ``delivery_hours`` (fastest).

All other entries' provider/item keys are recorded in
``AggregatedItem.duplicate_keys`` so an auditor can replay the merge.

The aggregator is a **pure function** — no I/O, no shared state, safe
to call concurrently from multiple coordinators if ever needed.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import defaultdict
from typing import Optional

from .models import (
    AggregatedItem,
    CatalogItem,
    NetworkFailure,
    NetworkResult,
    NetworkStatus,
)

logger = logging.getLogger(__name__)


#: Default great-circle distance threshold for geographic dedup, in km.
#: ~500 metres covers the common case of one BPP listing the same store
#: with slightly different GPS coordinates across two registries.
DEFAULT_GEO_PROXIMITY_KM: float = 0.5

# A primary signature key. Empty strings are permitted (missing tax_id
# or missing name short-circuits to the empty bucket, which then relies
# on the geographic refinement pass for merging).
_Signature = tuple[str, str, str]


# ─────────────────────────────────────────────────────────────────────────
# Normalisation helpers (pure)
# ─────────────────────────────────────────────────────────────────────────


def _normalize_text(s: Optional[str]) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop punctuation.

    Examples::

        "Cat-6  Cable" → "cat 6 cable"
        "Café  "        → "cafe"
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _normalize_tax_id(s: Optional[str]) -> str:
    """Uppercase, strip whitespace and hyphens — survives GST/PAN typos.

    Examples::

        " gst-123 "  → "GST123"
        "29ABCDE1234F1Z5" → "29ABCDE1234F1Z5"
    """
    if not s:
        return ""
    return re.sub(r"[\s\-]", "", s.upper())


def _parse_gps(coord: Optional[str]) -> Optional[tuple[float, float]]:
    """Parse a ``"lat,lon"`` string into a ``(lat, lon)`` float tuple.

    Returns ``None`` for malformed inputs (missing comma, non-numeric,
    out-of-range latitudes/longitudes).
    """
    if not coord:
        return None
    try:
        parts = [p.strip() for p in coord.split(",")]
        if len(parts) != 2:
            return None
        lat = float(parts[0])
        lon = float(parts[1])
    except (ValueError, AttributeError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between two ``(lat, lon)`` pairs."""
    earth_radius_km = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return earth_radius_km * 2.0 * math.asin(min(1.0, math.sqrt(h)))


def _signature(item: CatalogItem) -> _Signature:
    """Build the primary (tax_id, name, currency) dedup signature."""
    return (
        _normalize_tax_id(item.tax_id),
        _normalize_text(item.name),
        (item.currency or "INR").upper(),
    )


def _stable_key(item: CatalogItem) -> str:
    """Return a deterministic ``"{provider_id}:{item_id}"`` audit key."""
    return f"{item.provider_id}:{item.item_id}"


def _merge_score(item: CatalogItem) -> tuple[float, int, int]:
    """Tie-break tuple used to pick the canonical item in a duplicate group.

    Lower is better:

    * lowest ``price``,
    * then negative ``quantity_available`` (so larger is better via min),
    * then ``delivery_hours`` (so shorter is better via min).
    """
    qty = item.quantity_available if item.quantity_available is not None else 0
    delivery = item.delivery_hours if item.delivery_hours is not None else 10**9
    return (item.price, -qty, delivery)


# ─────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────


class ResultAggregator:
    """Combine multi-network results into a deduplicated catalog."""

    def __init__(self, *, geo_proximity_km: float = DEFAULT_GEO_PROXIMITY_KM) -> None:
        if geo_proximity_km < 0:
            raise ValueError("geo_proximity_km must be non-negative")
        self._geo_proximity_km = geo_proximity_km

    # ── Public ──────────────────────────────────────────────────────────

    def aggregate(
        self, results: list[NetworkResult]
    ) -> tuple[list[AggregatedItem], list[NetworkResult], list[NetworkFailure]]:
        """Aggregate ``results`` into a tuple of (items, successes, failures).

        Parameters
        ----------
        results:
            Heterogeneous list returned by the coordinator. Order is
            preserved through successes / failures separation for stable
            test assertions.

        Returns
        -------
        items:
            Deduplicated, price-sorted list of :class:`AggregatedItem`.
        successes:
            Subset of ``results`` whose status is ``OK``.
        failures:
            Compact :class:`NetworkFailure` records — *not* raw
            ``NetworkResult`` so we can serialise them straight into
            the API response.
        """
        successes = [r for r in results if r.is_success]
        failures = [
            NetworkFailure(
                network=r.network,
                status=r.status,
                error=r.error,
                latency_ms=r.latency_ms,
            )
            for r in results
            if not r.is_success
        ]

        # Stage 1 — bucket by primary signature.
        primary_buckets: dict[_Signature, list[tuple[CatalogItem, str]]] = defaultdict(list)
        for result in successes:
            for item in result.items:
                primary_buckets[_signature(item)].append((item, result.network))

        # Stage 2 — geo-refine within each bucket, then merge.
        aggregated: list[AggregatedItem] = []
        for sig, members in primary_buckets.items():
            tax_id_norm, name_norm, _currency = sig
            if tax_id_norm:
                # Confident match: same supplier tax id + same name.
                aggregated.extend(self._merge_confident(members))
            else:
                # No tax id — fall back on geographic proximity within
                # the name+currency bucket. Items without GPS in this
                # bucket are kept as separate (cannot prove they're dups).
                aggregated.extend(self._merge_by_geography(members))

        # Deterministic ordering: price ascending, then name, then provider.
        aggregated.sort(key=lambda i: (i.price, i.name, i.provider_id))
        return aggregated, successes, failures

    # ── Internal merge strategies ───────────────────────────────────────

    def _merge_confident(
        self, members: list[tuple[CatalogItem, str]]
    ) -> list[AggregatedItem]:
        """Merge a bucket where all members share the same normalised tax_id."""
        if not members:
            return []
        sources = sorted({network for _, network in members})
        canonical_item, _ = min(members, key=lambda x: _merge_score(x[0]))
        out = self._to_aggregated(canonical_item, sources)
        if len(members) > 1:
            out.duplicate_keys = sorted({_stable_key(it) for it, _ in members})
        return [out]

    def _merge_by_geography(
        self, members: list[tuple[CatalogItem, str]]
    ) -> list[AggregatedItem]:
        """Merge a bucket with no tax_id using GPS proximity.

        Items with parseable GPS within ``geo_proximity_km`` of each
        other cluster together. Items missing GPS form their own
        singleton cluster (no merging — we cannot prove identity).
        """
        if not members:
            return []
        n = len(members)
        used = [False] * n
        clusters: list[list[int]] = []

        for i in range(n):
            if used[i]:
                continue
            used[i] = True
            cluster = [i]
            gps_i = _parse_gps(members[i][0].location_coordinates)
            if gps_i is not None:
                for j in range(i + 1, n):
                    if used[j]:
                        continue
                    gps_j = _parse_gps(members[j][0].location_coordinates)
                    if gps_j is None:
                        continue
                    if _haversine_km(gps_i, gps_j) <= self._geo_proximity_km:
                        used[j] = True
                        cluster.append(j)
            clusters.append(cluster)

        out: list[AggregatedItem] = []
        for cluster in clusters:
            cluster_members = [members[k] for k in cluster]
            sources = sorted({network for _, network in cluster_members})
            canonical_item, _ = min(cluster_members, key=lambda x: _merge_score(x[0]))
            agg = self._to_aggregated(canonical_item, sources)
            if len(cluster_members) > 1:
                agg.duplicate_keys = sorted(
                    {_stable_key(it) for it, _ in cluster_members}
                )
            out.append(agg)
        return out

    @staticmethod
    def _to_aggregated(item: CatalogItem, sources: list[str]) -> AggregatedItem:
        """Project a :class:`CatalogItem` onto an :class:`AggregatedItem`."""
        return AggregatedItem(
            provider_id=item.provider_id,
            item_id=item.item_id,
            name=item.name,
            price=item.price,
            currency=item.currency,
            delivery_hours=item.delivery_hours,
            quantity_available=item.quantity_available,
            tax_id=item.tax_id,
            location_coordinates=item.location_coordinates,
            sources=sources,
            duplicate_keys=[],
        )


__all__ = [
    "DEFAULT_GEO_PROXIMITY_KM",
    "ResultAggregator",
]
