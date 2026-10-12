"""
Cryptographic primitives for End-to-End Encryption of the memory graph.

Design
------
- Keys are DERIVED from the user's PIN with PBKDF2-HMAC-SHA256 (310,000
  iterations, 32-byte output). The PIN itself is never stored anywhere.
- A random 32-byte salt is generated per user and persisted (as hex) in
  PostgreSQL. The salt only guarantees identical PINs yield different keys.
- Values are encrypted with AES-256-GCM. The stored blob is
  ``base64(nonce || ciphertext || tag)`` (16-byte GCM tag is appended by the
  ``cryptography`` library).

Frontend/Backend parity
-----------------------
These parameters MUST match the browser Web Crypto implementation in
``frontend/src/services/encryptionService.ts`` exactly, otherwise the key
derived on the client will not decrypt server-produced data:

    PBKDF2-HMAC-SHA256, 310,000 iterations, 32-byte key, 32-byte salt
"""

import base64
import os
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


# --- Constants (keep in sync with the frontend encryptionService.ts) ---
PBKDF2_ITERATIONS = 310_000
KEY_LENGTH_BYTES = 32          # 256-bit AES key
SALT_LENGTH_BYTES = 32         # 256-bit random salt
NONCE_LENGTH_BYTES = 12        # 96-bit nonce (recommended for GCM)
# GCM tag is 16 bytes (128-bit) by default, appended to the ciphertext.

# Sensitive node property names encrypted at rest in Neo4j.
# NOTE: In this project's graph schema the free-text content of facts and
# messages is stored under the property ``text`` (see schema.cypher and
# ingestion.py). The original spec listed ``fact_text``; we include BOTH the
# spec field names AND the real schema field ``text`` so the actual financial
# content is genuinely encrypted.
FIELDS_TO_ENCRYPT: List[str] = [
    "fact_text",   # spec field (future-proofing / alternative extractors)
    "text",        # real Fact/Message/Preference/DocumentChunk text property
    "amount",      # Transaction amount
    "price",       # price fields
    "value",       # Asset value
    "notes",       # free-form notes
    "description", # descriptions
]


def generate_salt() -> str:
    """Generate a cryptographically-random per-user salt.

    Returns:
        A 32-byte random salt encoded as a hex string (64 hex chars).
    """
    return os.urandom(SALT_LENGTH_BYTES).hex()


def derive_key(pin: str, salt: str) -> bytes:
    """Derive a 32-byte AES-256 key from a PIN and salt using PBKDF2.

    Uses PBKDF2-HMAC-SHA256 with 310,000 iterations to resist brute force.

    Args:
        pin: The user's PIN (plaintext). Never stored.
        salt: Hex-encoded salt string (as produced by ``generate_salt``).

    Returns:
        The derived 32-byte key as raw bytes.
    """
    if pin is None:
        raise ValueError("PIN must not be None")
    if not salt:
        raise ValueError("Salt must not be empty")

    salt_bytes = bytes.fromhex(salt)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH_BYTES,
        salt=salt_bytes,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(pin.encode("utf-8"))


def encrypt_field(value: str, key: bytes) -> str:
    """Encrypt a single string field with AES-256-GCM.

    Args:
        value: Plaintext string to encrypt.
        key: 32-byte AES key (raw bytes) from ``derive_key``.

    Returns:
        Base64-encoded string of ``nonce(12) || ciphertext || tag(16)``.
    """
    if value is None:
        return value

    plaintext = (
        value.encode("utf-8")
        if isinstance(value, str)
        else str(value).encode("utf-8")
    )
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_LENGTH_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)  # tag appended
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_field(encrypted: str, key: bytes) -> str:
    """Decrypt a single field produced by ``encrypt_field``.

    Args:
        encrypted: Base64 string of ``nonce || ciphertext || tag``.
        key: 32-byte AES key (raw bytes).

    Returns:
        The original plaintext string.

    Raises:
        ValueError: If the blob is malformed or authentication fails (wrong
            key / tampered data).
    """
    if encrypted is None:
        return encrypted

    try:
        blob = base64.b64decode(encrypted)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid base64 ciphertext: {exc}")

    if len(blob) <= NONCE_LENGTH_BYTES:
        raise ValueError("Ciphertext too short to contain a nonce")

    nonce = blob[:NONCE_LENGTH_BYTES]
    ciphertext = blob[NONCE_LENGTH_BYTES:]

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:  # noqa: BLE001 - InvalidTag on wrong key
        raise ValueError(f"Decryption failed (wrong key or corrupted data): {exc}")

    return plaintext.decode("utf-8")


def _is_probably_encrypted(value: Any) -> bool:
    """Heuristic to detect whether a value is already an encrypted blob.

    Avoids double-encrypting data that is already ciphertext. A value from
    ``encrypt_field`` is a base64 string whose decoded length is at least
    12 (nonce) + 16 (tag) = 28 bytes.
    """
    if not isinstance(value, str) or not value:
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:  # noqa: BLE001
        return False
    return len(decoded) > NONCE_LENGTH_BYTES


def encrypt_node_properties(
    properties: Dict[str, Any],
    key: bytes,
    fields_to_encrypt: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a copy of ``properties`` with sensitive fields encrypted.

    Only fields listed in ``fields_to_encrypt`` (defaults to
    ``FIELDS_TO_ENCRYPT``) that are present and not ``None`` are encrypted.
    Already-encrypted values are left untouched to prevent double encryption.
    Non-string scalars (e.g. numeric amounts) are stringified so the property
    is stored as an opaque base64 blob.

    Args:
        properties: The node property dict.
        key: 32-byte AES key.
        fields_to_encrypt: Optional override of the sensitive field list.

    Returns:
        A new dict with sensitive fields replaced by ciphertext.
    """
    if not key or not properties:
        return properties

    fields = fields_to_encrypt if fields_to_encrypt is not None else FIELDS_TO_ENCRYPT
    result = dict(properties)

    for field in fields:
        if field not in result:
            continue
        value = result[field]
        if value is None:
            continue
        if _is_probably_encrypted(value):
            continue  # already ciphertext, do not double-encrypt
        result[field] = encrypt_field(value, key)

    return result


def decrypt_node_properties(
    properties: Dict[str, Any],
    key: bytes,
    fields_to_encrypt: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a copy of ``properties`` with sensitive fields decrypted.

    Values that fail to decrypt (wrong key, or plaintext written before
    encryption was enabled) are left as-is so a single bad field does not break
    the whole node. This makes decryption resilient during migration and across
    mixed plaintext/ciphertext graphs.

    Args:
        properties: The node property dict (possibly containing ciphertext).
        key: 32-byte AES key.
        fields_to_encrypt: Optional override of the sensitive field list.

    Returns:
        A new dict with sensitive fields decrypted to plaintext.
    """
    if not key or not properties:
        return properties

    fields = fields_to_encrypt if fields_to_encrypt is not None else FIELDS_TO_ENCRYPT
    result = dict(properties)

    for field in fields:
        if field not in result:
            continue
        value = result[field]
        if not isinstance(value, str) or not value:
            continue
        if not _is_probably_encrypted(value):
            continue  # legacy plaintext, leave untouched
        try:
            result[field] = decrypt_field(value, key)
        except ValueError:
            # Wrong key or corrupted value: keep original so the caller still
            # receives a usable node instead of an exception.
            continue

    return result

