"""
Encryption package for GraphMind End-to-End Encryption (E2EE).

Provides:
- crypto_service: Low-level cryptographic primitives (PBKDF2 key derivation,
  AES-256-GCM field encryption) that mirror the browser Web Crypto API so the
  frontend and backend derive byte-identical keys.
- encryption_service: High-level orchestration that persists per-user salts in
  PostgreSQL and (re)encrypts Neo4j node properties.

Security model:
- The user's PIN is NEVER stored. Only a random per-user salt is persisted.
- The derived key exists only in memory (server) / sessionStorage (browser)
  during an active session and is sent per-request via the X-Encryption-Key
  header. The server never logs or persists that key.
"""
