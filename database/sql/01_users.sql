-- 01_users.sql
-- Entity 1: User
-- Person interacting with the system. Defines RBAC role and approval threshold.
-- Store: PostgreSQL 16 · IdP: Keycloak SSO (SAML 2.0 / OIDC)

CREATE TABLE IF NOT EXISTS users (
    user_id             UUID                PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               VARCHAR(255)        NOT NULL UNIQUE,
    name                VARCHAR(255)        NOT NULL,
    role                user_role           NOT NULL,
    department          VARCHAR(100)        NOT NULL,
    approval_threshold  DECIMAL(15,2)       NOT NULL DEFAULT 0.00
                                            CHECK (approval_threshold >= 0),
    keycloak_id         VARCHAR(255)        NOT NULL UNIQUE,
    idp_provider        idp_provider_type   NOT NULL,
    created_at          TIMESTAMP           NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS
    'Persons interacting with the system. RBAC role determines operations and approval threshold.';
COMMENT ON COLUMN users.approval_threshold IS
    'Maximum amount in local currency the user can approve without escalation.';
COMMENT ON COLUMN users.keycloak_id IS
    'sub claim of the JWT issued by Keycloak / OIDC provider.';
