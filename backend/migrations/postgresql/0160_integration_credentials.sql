-- Midar 0.16.0 - reviewed migration for an existing PostgreSQL Midar database.
-- Preconditions: organizations, social_accounts, users, and oauth_transactions tables already exist.
-- Apply during a backup window before enabling any provider OAuth callback that uses the credential store.
BEGIN;
CREATE TABLE IF NOT EXISTS integration_credentials (
    id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    social_account_id VARCHAR(36) NOT NULL UNIQUE REFERENCES social_accounts(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    access_token_ciphertext TEXT NOT NULL,
    refresh_token_ciphertext TEXT NULL,
    token_type VARCHAR(32) NOT NULL DEFAULT 'Bearer',
    scopes_json TEXT NOT NULL DEFAULT '[]',
    expires_at TIMESTAMP WITH TIME ZONE NULL,
    key_format VARCHAR(24) NOT NULL DEFAULT 'fernet:v1',
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    created_by VARCHAR(36) NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_integration_credentials_org_provider
    ON integration_credentials (organization_id, provider);
CREATE INDEX IF NOT EXISTS ix_integration_credentials_organization_id
    ON integration_credentials (organization_id);

-- Browser binding for generic social-provider OAuth transactions. Existing Google
-- OAuth tables are not altered by this additive table.
CREATE TABLE IF NOT EXISTS provider_oauth_bindings (
    state_hash VARCHAR(64) PRIMARY KEY REFERENCES oauth_transactions(state_hash) ON DELETE CASCADE,
    browser_binding_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);
COMMIT;
