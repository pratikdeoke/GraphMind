# End-to-End Encryption (E2EE) of the Memory Graph

GraphMind encrypts sensitive financial data **at rest** in Neo4j using
**AES-256-GCM**, with keys **derived from the user's PIN** via **PBKDF2**.
The server never stores the PIN or the derived key — only a random per-user
salt. The key lives only in the browser's `sessionStorage` during a session
and is sent per-request via the `X-Encryption-Key` header.

---

## Security model (threat model)

| Asset | Where it lives | Encrypted? |
|-------|----------------|-----------|
| PIN | Never stored. Transient only (client input). | n/a |
| Derived AES-256 key | Browser `sessionStorage` (cleared on tab close). Sent in `X-Encryption-Key` header per request. Used in-memory server-side only for that request. | n/a (it IS the secret) |
| Per-user salt | PostgreSQL `users.encryption_salt` (hex). Public-ish; prevents rainbow tables. | plaintext (not secret) |
| Sensitive graph fields | Neo4j node properties. | **AES-256-GCM at rest** |

**What this protects:** anyone who gains read access to the Neo4j database
(dump, backup, insider, DB compromise) cannot read the financial facts,
amounts, or notes without the user's PIN.

**What it does NOT protect:** a fully compromised *application server* that
logs request headers (we explicitly do not) or an attacker with the live
session key in the browser. The key is intentionally transmitted for the
duration of a session to enable search/ranking server-side.

---

## Cryptographic parameters (must match on both sides)

```
KDF:        PBKDF2-HMAC-SHA256
Iterations: 310,000
Salt:       32 random bytes (per user, stored as hex)
Key:        32 bytes (256-bit AES)
Cipher:     AES-256-GCM
Nonce:      12 random bytes (per field)
Tag:        16 bytes (appended to ciphertext by the library)
Stored blob: base64( nonce(12) || ciphertext || tag(16) )
```

Backend: `backend/services/encryption/crypto_service.py`
Frontend: `frontend/src/services/encryptionService.ts`

> ⚠️ If you change any parameter (iterations, salt length, key length) you MUST
> change it in **both** files, otherwise client-derived keys won't decrypt
> server-encrypted data.

---

## Encrypted fields

`FIELDS_TO_ENCRYPT` (in `crypto_service.py`):

```python
["fact_text", "text", "amount", "price", "value", "notes", "description"]
```

Note: your graph schema stores fact/message content under the property
**`text`** (not `fact_text`), transaction amounts under **`amount`**, and asset
values under **`value`/`amount`**. The list includes both the original spec
field names and the real schema fields so the actual content is encrypted.
Structural fields (`id`, `user_id`, `name`, `entity_type`, timestamps,
`confidence`) are left in plaintext so graph traversal, MERGE keys, and
user-isolation keep working.

---

## Backend files

| File | Purpose |
|------|---------|
| `services/encryption/crypto_service.py` | PBKDF2 + AES-256-GCM primitives, node-property (de/en)cryption, `FIELDS_TO_ENCRYPT`. |
| `services/encryption/encryption_service.py` | Orchestration: setup / verify / change-pin / disable + Neo4j re-encryption. Lazy singleton. |
| `api/routes/encryption.py` | The 5 endpoints. Requires Bearer JWT. |
| `api/models_encryption.py` | Pydantic request/response models. |
| `api/routes/chat.py` | Accepts `X-Encryption-Key` header, threads key to ingest + retrieve. |
| `api/routes/memory.py` | Mindmap decrypts node fields when the key header is present. |
| `services/graph/ingestion.py` | `ingest_memory(..., encryption_key=)` encrypts fields before write. |
| `services/graph/retrieval.py` | `retrieve(..., encryption_key=)` decrypts fields after ranking. |
| `services/graph/mindmap_service.py` | `get_user_graph(..., encryption_key=)` decrypts for visualization. |
| `services/orchestrator/*.py` | Thread `encryption_key` from the endpoint down to the graph services. |
| `services/database/user_service.py` | Salt/flag/hint persistence (never the PIN or key). |
| `database/init.sql` + `database/migrations/20261011_add_encryption_columns.sql` | New `users` columns. |

### Endpoints

```
POST   /encryption/setup       { pin, hint? }         -> { salt, success, nodes_encrypted }
POST   /encryption/verify-pin  { pin }                -> { salt, valid }   (client derives key)
POST   /encryption/change-pin  { old_pin, new_pin }   -> { success, nodes_reencrypted }
DELETE /encryption/disable     { pin }                -> { success, nodes_decrypted }
GET    /encryption/status                            -> { encryption_enabled, hint }
```

All require `Authorization: Bearer <jwt>`.

### Chat / Mindmap header

`/chat` and `/memory/mindmap` accept an optional base64-encoded raw 32-byte key
in the `X-Encryption-Key` header. It is decoded, used only in-memory for that
request, and **never logged or stored**. A malformed/short header is ignored
(request proceeds without E2EE).

---

## Frontend files

| File | Purpose |
|------|---------|
| `services/encryptionService.ts` | `deriveKey`, `exportKey`, sessionStorage helpers, `deriveAndStoreKey`. |
| `components/EncryptionSetup.tsx` | Modal with `setup` (after signup) and `unlock` (after login) modes. |
| `lib/api.ts` | `encryptionAPI` + axios interceptor that auto-attaches `X-Encryption-Key`. |
| `pages/Signup.tsx` | Shows the setup modal after successful signup (skippable). |
| `pages/Login.tsx` | Checks status; if enabled, shows unlock modal before entering. |
| `contexts/AuthContext.tsx` | Clears the session key on logout. |
| `.env` | Points the frontend at `http://localhost:8001`. |

---

## User flows

### First-time setup (after signup)
1. Signup succeeds → `EncryptionSetup` modal appears (mode `setup`).
2. User picks a PIN (+ optional hint) → `POST /encryption/setup`.
3. Backend generates a salt, stores it + `encryption_enabled=true`, encrypts
   any existing nodes, and returns the `salt`.
4. Client derives the AES key from PIN + salt (PBKDF2) and stores the base64
   key in `sessionStorage`.
5. Every subsequent `/chat` request auto-includes `X-Encryption-Key`.

### Returning user (login)
1. Login succeeds → frontend calls `GET /encryption/status`.
2. If `encryption_enabled`, show `EncryptionSetup` (mode `unlock`) with the hint.
3. `POST /encryption/verify-pin` returns the salt (and validates the PIN).
4. Client derives + stores the key in `sessionStorage`.

### Change PIN
`POST /encryption/change-pin` verifies the old PIN against a sample node,
generates a new salt, decrypts every node with the old key and re-encrypts with
the new key, then persists the new salt. The client re-derives with the new PIN.

### Disable
`DELETE /encryption/disable` decrypts all nodes back to plaintext, sets
`encryption_enabled=false`, and removes the salt.

---

## Known trade-offs (inherent to E2EE with a client-held key)

1. **No server-side plaintext search / dedup.** AES-GCM uses a random nonce, so
   identical plaintext yields different ciphertext. Exact-text deduplication and
   the contradiction heuristic in ingestion cannot match already-encrypted
   facts; under encryption each incoming fact becomes a new node. Retrieval
   ranking runs on ciphertext and only the returned fields are decrypted.
2. **Mindmap/sidebar numeric aggregation** (e.g. summing `amount` in Cypher)
   operates on ciphertext. Those aggregate endpoints would need the key too, or
   must be run client-side after decryption.
3. **Forgotten PIN = unrecoverable data.** By design, the PIN is never stored.

---

## Setup checklist (for the user)

1. Apply the migration (or recreate the DB):
   ```
   psql -f backend/database/migrations/20261011_add_encryption_columns.sql
   ```
   (or re-run `backend/database/init.sql` on a fresh database).
2. `pip install -r backend/requirements.txt` (adds `cryptography`).
3. Restart the backend (`uvicorn api.main:app --port 8001`).
4. Frontend: `npm install && npm run dev` (`.env` points to `:8001`).
5. Test the primitives without a DB:
   ```
   python backend/test_e2ee.py
   ```

