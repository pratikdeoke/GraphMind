-- Add End-to-End Encryption (E2EE) columns to the users table.
-- Safe to run multiple times on PostgreSQL.
--
-- encryption_salt: random per-user salt (hex) used with PBKDF2 to derive the
--   AES-256 key from the user's PIN. The PIN itself is NEVER stored server-side.
-- encryption_enabled: whether the user's Neo4j nodes are encrypted at rest.
-- encryption_hint: optional user-provided hint to remember their PIN.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS encryption_salt VARCHAR(64);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS encryption_enabled BOOLEAN DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS encryption_hint VARCHAR(255);

COMMENT ON COLUMN users.encryption_salt IS 'Per-user PBKDF2 salt (hex) for E2EE key derivation. PIN never stored.';
COMMENT ON COLUMN users.encryption_enabled IS 'Whether the user memory graph is encrypted at rest in Neo4j.';
COMMENT ON COLUMN users.encryption_hint IS 'Optional user hint to remember their encryption PIN.';
