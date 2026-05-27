"""Webhook HMAC verification with dual-secret rotation support.

Header format accepted (case-insensitive prefix):
    sha256=<lowercase hex>

The verifier accepts ANY of the supplied secrets — this enables zero-downtime
rotation: set `{VENDOR}_WEBHOOK_HMAC_SECRET_NEXT`, deploy, switch vendor to
sign with NEXT, deploy again with NEXT promoted to primary, clear NEXT.

Constant-time compare via `hmac.compare_digest` — never log the supplied
signature or the secret(s).
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
from typing import Iterable


_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Compute the canonical `sha256=<hex>` header value for `body`."""
    return _PREFIX + _hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def parse_signature_header(header_value: str | None) -> str | None:
    """Return the raw hex digest from a header, or None if malformed.

    Tolerates the `sha256=` prefix being absent (some vendors omit it).
    Strips whitespace.
    """
    if not header_value:
        return None
    v = header_value.strip()
    if v.lower().startswith(_PREFIX):
        v = v[len(_PREFIX):]
    v = v.strip()
    if not v:
        return None
    return v.lower()


def verify_signature(
    *,
    raw_body: bytes,
    header_value: str | None,
    secrets: Iterable[str],
) -> bool:
    """True if `header_value` matches the signature of `raw_body` under ANY
    of the provided non-empty secrets.

    Both empty strings and None secrets are skipped so callers can blindly
    pass `(primary, next_or_empty)` without filtering.
    """
    parsed = parse_signature_header(header_value)
    if parsed is None:
        return False
    for secret in secrets:
        if not secret:
            continue
        expected = _hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if _hmac.compare_digest(expected, parsed):
            return True
    return False
