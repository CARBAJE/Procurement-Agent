"""users table — just-in-time provisioning of the authenticated Keycloak user.

The real user identity lives in Keycloak (next-auth). This resolves that
identity to a local `users.user_id` so requests/orders are attributed to the
real person instead of the System Agent. Keyed by `keycloak_id` (the JWT `sub`).
"""
from __future__ import annotations

import logging
import uuid as _uuid

logger = logging.getLogger(__name__)

# users.role is the `user_role` enum: requester | approver | admin.
_VALID_ROLES = {"requester", "approver", "admin"}


async def resolve_user(
    conn,
    keycloak_id: str,
    email: str | None,
    name: str | None,
    role: str | None,
) -> str:
    """Find-or-create a users row for a Keycloak identity; return user_id (str).

    Idempotent on keycloak_id. Refreshes name/role/email on re-login (Keycloak
    is the source of truth). Handles the email-UNIQUE collision with a seeded
    row by linking that row's keycloak_id. Caller passes its own connection so
    this can run inside the request-creation transaction.
    """
    # 1. Already provisioned?
    row = await conn.fetchrow(
        "SELECT user_id FROM users WHERE keycloak_id = $1", keycloak_id
    )
    if row:
        return str(row["user_id"])

    safe_role = role if role in _VALID_ROLES else "requester"
    safe_email = email or f"{keycloak_id}@keycloak.local"
    safe_name = name or email or keycloak_id

    # 2. Insert (idempotent on keycloak_id; refresh mutable fields on re-login).
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO users
                (email, name, role, department,
                 approval_threshold, keycloak_id, idp_provider)
            VALUES ($1, $2, $3::user_role, 'Procurement', 0.00, $4, 'keycloak')
            ON CONFLICT (keycloak_id) DO UPDATE
                SET name = EXCLUDED.name, role = EXCLUDED.role
            RETURNING user_id
            """,
            safe_email, safe_name, safe_role, keycloak_id,
        )
        return str(row["user_id"])
    except Exception as exc:  # noqa: BLE001 — most likely the email UNIQUE collision
        logger.warning(
            "[user_repo] insert for keycloak_id=%s hit %s — linking by email",
            keycloak_id, type(exc).__name__,
        )

    # 3. email already belongs to a seeded/other row → link it to this kc id.
    row = await conn.fetchrow(
        """
        UPDATE users SET keycloak_id = $1
        WHERE email = $2
        RETURNING user_id
        """,
        keycloak_id, safe_email,
    )
    if row:
        return str(row["user_id"])

    # 4. Could not resolve — let the caller fall back to the system user.
    raise ValueError(f"could not resolve user for keycloak_id={keycloak_id!r}")
