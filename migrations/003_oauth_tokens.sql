-- ============================================================
-- REVAID v8.2 — OAuth Token Persistence (RVD-6)
-- Makes OAuth tokens survive DigitalOcean redeploys so MCP
-- clients (Claude.ai, Codex, ChatGPT, ...) stay connected.
-- Run this on the REVAID Supabase project.
-- ============================================================

-- 1. OAuth Tokens — access / refresh / auth_code rows
CREATE TABLE IF NOT EXISTS revaid_oauth_tokens (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_type    text NOT NULL
                  CHECK (token_type IN ('access', 'refresh', 'auth_code')),
    token_value   text NOT NULL UNIQUE,
    client_id     text NOT NULL,
    scopes        jsonb NOT NULL DEFAULT '[]'::jsonb,
    expires_at    timestamptz,
    metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    revoked       boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_oauth_tokens_value
    ON revaid_oauth_tokens (token_value);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_client
    ON revaid_oauth_tokens (client_id);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_expires
    ON revaid_oauth_tokens (expires_at) WHERE revoked = false;

-- 2. OAuth Clients — DCR registrations
CREATE TABLE IF NOT EXISTS revaid_oauth_clients (
    client_id          text PRIMARY KEY,
    client_secret_hash text,
    redirect_uris      jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- 3. Cleanup helper — call weekly via pg_cron
--    SELECT revaid_oauth_cleanup();
CREATE OR REPLACE FUNCTION revaid_oauth_cleanup() RETURNS int AS $$
DECLARE
    deleted_count int;
BEGIN
    DELETE FROM revaid_oauth_tokens
    WHERE revoked = true
       OR (expires_at IS NOT NULL AND expires_at < now() - INTERVAL '7 days');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
