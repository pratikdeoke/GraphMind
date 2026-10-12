"""
Encryption Service - Orchestrates E2EE of the memory graph.

Coordinates PostgreSQL (salt / flags) and Neo4j (node properties) to:
- enable encryption for a user (generate salt, encrypt existing nodes)
- verify a PIN (server best-effort check; client keeps the derived key)
- change a PIN (decrypt all nodes with old key, re-encrypt with new key)
- disable encryption (decrypt all nodes back to plaintext)

SECURITY: This service NEVER stores or logs the user's PIN or the derived key.
The derived key is passed in transiently (as raw bytes) and used only for the
duration of the operation.
"""

import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from config.settings import Settings
from services.database.user_service import UserService
from services.encryption.crypto_service import (
    FIELDS_TO_ENCRYPT,
    decrypt_field,
    decrypt_node_properties,
    derive_key,
    encrypt_field,
    encrypt_node_properties,
    generate_salt,
)

logger = logging.getLogger(__name__)


# --- PIN-verification canary ---------------------------------------------
# A single Neo4j node holding ONE field encrypted with the user's key. Because
# setup() may run before the user has ANY memory nodes, PIN verification
# (verify-pin / change-pin) would otherwise have nothing to test-decrypt and
# would have to accept ANY PIN. The canary guarantees there is always exactly
# one ciphertext that only the correct PIN's key can authenticate (AES-GCM tag).
# The plaintext is a fixed, meaningless string; it leaks nothing.
CANARY_LABEL = "EncryptionCanary"
CANARY_PLAINTEXT = "graphmind-e2ee-canary-v1"
# Property name is intentionally one of FIELDS_TO_ENCRYPT so existing
# decrypt/scan helpers treat it like any other sensitive field.
CANARY_FIELD = "text"


class EncryptionService:
    """High-level orchestration for end-to-end encryption of the graph."""

    def __init__(self):
        """Initialize Neo4j driver and user service."""
        self.user_service = UserService()
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not connect to Neo4j for encryption service: %s", exc)
            self.driver = None

    # ------------------------------------------------------------------
    # Status / salt retrieval
    # ------------------------------------------------------------------
    def get_status(self, user_id: str) -> Dict[str, Any]:
        """Return encryption status for a user (never includes the salt)."""
        profile = self.user_service.get_encryption_profile(user_id)
        if not profile:
            return {"encryption_enabled": False, "hint": None}
        return {
            "encryption_enabled": bool(profile.get("encryption_enabled")),
            "hint": profile.get("encryption_hint"),
        }

    def get_salt(self, user_id: str) -> Optional[str]:
        """Return the user's stored salt so the client can derive the key."""
        profile = self.user_service.get_encryption_profile(user_id)
        if not profile:
            return None
        return profile.get("encryption_salt")

    def is_enabled(self, user_id: str) -> bool:
        """Whether encryption is currently enabled for the user."""
        return bool(self.get_status(user_id).get("encryption_enabled"))

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def setup(
        self,
        user_id: str,
        neo4j_user_id: str,
        pin: str,
        hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enable encryption: generate salt, persist it, encrypt existing nodes.

        The PIN is used only to derive a working key locally (to encrypt any
        pre-existing plaintext nodes). It is never stored.

        Args:
            user_id: PostgreSQL user UUID.
            neo4j_user_id: Neo4j user node id (node ownership).
            pin: The user's chosen PIN (transient, never persisted).
            hint: Optional PIN hint.

        Returns:
            Dict with the salt and number of nodes encrypted.
        """
        salt = generate_salt()
        key = derive_key(pin, salt)  # verify derivation works + use to encrypt

        # Persist salt + flags BEFORE touching Neo4j so a crash mid-way is
        # detectable (nodes remain readable as ciphertext once written).
        self.user_service.enable_encryption(user_id, salt, hint)

        nodes_encrypted = 0
        if self.driver:
            nodes_encrypted = self._encrypt_all_nodes(neo4j_user_id, key)
            # Canary lets verify-pin reject a WRONG PIN even when the user has
            # zero memory nodes (AES-GCM auth-tag check against known ciphertext).
            self._ensure_canary(neo4j_user_id, key)

        return {"salt": salt, "success": True, "nodes_encrypted": nodes_encrypted}

    # ------------------------------------------------------------------
    # Verify PIN
    # ------------------------------------------------------------------
    def verify_pin(self, user_id: str, neo4j_user_id: Optional[str], pin: str) -> bool:
        """Best-effort server-side check that a PIN can decrypt existing data.

        The client derives and keeps the key; this check just tries to decrypt
        one already-encrypted node to give immediate feedback on a wrong PIN.
        Returns True when there is no encrypted data yet (nothing can
        contradict the PIN) or when a sample node decrypts successfully.

        Args:
            user_id: PostgreSQL user UUID.
            neo4j_user_id: Neo4j user node id (may be None).
            pin: The PIN to verify (transient).

        Returns:
            True if the PIN appears valid.
        """
        salt = self.get_salt(user_id)
        if not salt:
            return False  # encryption not enabled -> cannot verify

        key = derive_key(pin, salt)
        if not self.driver:
            return True  # cannot check without Neo4j; assume OK

        return self._can_decrypt_existing(neo4j_user_id, key)
    # ------------------------------------------------------------------
    # Change PIN
    # ------------------------------------------------------------------
    def change_pin(
        self,
        user_id: str,
        neo4j_user_id: str,
        old_pin: str,
        new_pin: str,
    ) -> Dict[str, Any]:
        """Change the PIN: verify old, re-encrypt all nodes with the new key.

        Args:
            user_id: PostgreSQL user UUID.
            neo4j_user_id: Neo4j user node id.
            old_pin: Current PIN (transient).
            new_pin: New PIN (transient).

        Returns:
            Dict with success flag and number of nodes re-encrypted.

        Raises:
            ValueError: If the old PIN cannot decrypt existing data.
        """
        old_salt = self.get_salt(user_id)
        if not old_salt:
            raise ValueError("Encryption is not enabled for this user")

        old_key = derive_key(old_pin, old_salt)

        # Verify the old PIN can decrypt at least one existing node.
        if self.driver and not self._can_decrypt_existing(neo4j_user_id, old_key):
            raise ValueError("Old PIN is incorrect")

        new_salt = generate_salt()
        new_key = derive_key(new_pin, new_salt)

        nodes_reencrypted = 0
        if self.driver:
            nodes_reencrypted = self._reencrypt_all_nodes(neo4j_user_id, old_key, new_key)
            # Re-bind the canary to the NEW key so subsequent verify-pin calls
            # validate against the updated PIN (old PIN now fails).
            self._ensure_canary(neo4j_user_id, new_key)

        # Persist the new salt only AFTER successful re-encryption.
        self.user_service.update_encryption_salt(user_id, new_salt, hint=None)

        return {"success": True, "nodes_reencrypted": nodes_reencrypted}

    # ------------------------------------------------------------------
    # Disable
    # ------------------------------------------------------------------
    def disable(self, user_id: str, neo4j_user_id: str, pin: str) -> Dict[str, Any]:
        """Disable encryption: decrypt all nodes to plaintext, clear salt.

        Args:
            user_id: PostgreSQL user UUID.
            neo4j_user_id: Neo4j user node id.
            pin: The current PIN (transient) used to derive the decryption key.

        Returns:
            Dict with success flag and number of nodes decrypted.

        Raises:
            ValueError: If encryption is not enabled or the PIN is wrong.
        """
        salt = self.get_salt(user_id)
        if not salt:
            raise ValueError("Encryption is not enabled for this user")

        key = derive_key(pin, salt)

        nodes_decrypted = 0
        if self.driver:
            if not self._can_decrypt_existing(neo4j_user_id, key):
                raise ValueError("PIN is incorrect")
            nodes_decrypted = self._decrypt_all_nodes(neo4j_user_id, key)
            # Remove the PIN-verification canary entirely -- with E2EE off,
            # no ciphertext should remain.
            self._delete_canary(neo4j_user_id)

        self.user_service.disable_encryption(user_id)
        return {"success": True, "nodes_decrypted": nodes_decrypted}

    # ------------------------------------------------------------------
    # Neo4j helpers
    # ------------------------------------------------------------------
    def _get_user_nodes(self, neo4j_user_id: str) -> List[Dict[str, Any]]:
        """Fetch all nodes owned by the user with their Neo4j internal id."""
        if not self.driver:
            return []
        query = """
        MATCH (n {user_id: $user_id})
        RETURN id(n) AS node_internal_id, properties(n) AS props
        """
        nodes: List[Dict[str, Any]] = []
        with self.driver.session() as session:
            result = session.run(query, user_id=neo4j_user_id)
            for record in result:
                nodes.append(
                    {
                        "node_internal_id": record["node_internal_id"],
                        "props": dict(record["props"]),
                    }
                )
        return nodes

    def _write_node_properties(self, node_internal_id: int, props: Dict[str, Any]) -> None:
        """Overwrite a node's properties via its internal id."""
        if not self.driver:
            return
        query = """
        MATCH (n)
        WHERE id(n) = $node_id
        SET n = $props
        """
        with self.driver.session() as session:
            session.run(query, node_id=node_internal_id, props=props)

    def _encrypt_all_nodes(self, neo4j_user_id: str, key: bytes) -> int:
        """Encrypt sensitive fields on every node owned by the user."""
        count = 0
        for node in self._get_user_nodes(neo4j_user_id):
            new_props = encrypt_node_properties(node["props"], key)
            if new_props != node["props"]:
                self._write_node_properties(node["node_internal_id"], new_props)
                count += 1
        return count

    def _decrypt_all_nodes(self, neo4j_user_id: str, key: bytes) -> int:
        """Decrypt sensitive fields on every node owned by the user."""
        count = 0
        for node in self._get_user_nodes(neo4j_user_id):
            new_props = decrypt_node_properties(node["props"], key)
            if new_props != node["props"]:
                self._write_node_properties(node["node_internal_id"], new_props)
                count += 1
        return count

    def _reencrypt_all_nodes(self, neo4j_user_id: str, old_key: bytes, new_key: bytes) -> int:
        """Decrypt with old_key then re-encrypt with new_key on every node."""
        count = 0
        for node in self._get_user_nodes(neo4j_user_id):
            decrypted = decrypt_node_properties(node["props"], old_key)
            reencrypted = encrypt_node_properties(decrypted, new_key)
            if reencrypted != node["props"]:
                self._write_node_properties(node["node_internal_id"], reencrypted)
                count += 1
        return count

    def _ensure_canary(self, neo4j_user_id: str, key: bytes) -> None:
        """Create or refresh the PIN-verification canary node.

        Writes a single node ``(:EncryptionCanary {user_id, text})`` whose
        ``text`` property is AES-256-GCM encrypted with ``key``. verify-pin and
        change-pin test-decrypt this value to decide whether a PIN is correct.
        Called from setup() and change_pin() only -- NEVER with an unverified
        PIN, so an attacker cannot overwrite it with a wrong-key ciphertext.
        """
        if not self.driver or not neo4j_user_id:
            return
        ciphertext = encrypt_field(CANARY_PLAINTEXT, key)
        query = f"""
        MERGE (c:{CANARY_LABEL} {{user_id: $user_id}})
        SET c.{CANARY_FIELD} = $canary, c.kind = 'encryption_canary'
        """
        try:
            with self.driver.session() as session:
                session.run(query, user_id=neo4j_user_id, canary=ciphertext)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write encryption canary: %s", exc)

    def _delete_canary(self, neo4j_user_id: str) -> None:
        """Remove the PIN-verification canary (used when disabling E2EE)."""
        if not self.driver or not neo4j_user_id:
            return
        query = f"MATCH (c:{CANARY_LABEL} {{user_id: $user_id}}) DETACH DELETE c"
        try:
            with self.driver.session() as session:
                session.run(query, user_id=neo4j_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete encryption canary: %s", exc)

    def _canary_decrypts(self, neo4j_user_id: str, key: bytes):
        """Test-decrypt the canary. Returns True/False, or None if no canary.

        Absence of a canary (legacy users who enabled E2EE before this
        mechanism existed) returns None so callers can fall back to scanning
        any other encrypted node before deciding.
        """
        if not self.driver or not neo4j_user_id:
            return None
        query = f"""
        MATCH (c:{CANARY_LABEL} {{user_id: $user_id}})
        RETURN c.{CANARY_FIELD} AS canary
        LIMIT 1
        """
        try:
            with self.driver.session() as session:
                record = session.run(query, user_id=neo4j_user_id).single()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read encryption canary: %s", exc)
            return None
        if record is None or not record["canary"]:
            return None
        try:
            decrypt_field(record["canary"], key)
            return True
        except ValueError:
            return False

    def _can_decrypt_existing(self, neo4j_user_id: Optional[str], key: bytes) -> bool:
        """Return True if the key can decrypt the user's existing ciphertext.

        Order of proof:
        1. The PIN-verification canary (authoritative; always present for
           users who set up E2EE after this fix).
        2. Any other encrypted node field (legacy fallback).
        3. If there is NO encrypted data at all, the PIN cannot be
           contradicted, so return True (nothing to decrypt).
        """
        if not self.driver:
            return True

        canary_ok = self._canary_decrypts(neo4j_user_id or "", key)
        if canary_ok is not None:
            return canary_ok

        sample = self._get_one_encrypted_node(neo4j_user_id, key)
        if sample is None:
            return True  # no encrypted data to check against
        return sample

    def _get_one_encrypted_node(
        self,
        neo4j_user_id: Optional[str],
        key: bytes,
    ) -> Optional[bool]:
        """Try to decrypt a single encrypted field to validate a key.

        Returns:
            True if a sample field decrypted successfully; False if a sample
            existed but failed to decrypt; None if no encrypted field was found.
        """
        if not self.driver:
            return None

        if neo4j_user_id:
            query = """
            MATCH (n {user_id: $user_id})
            RETURN properties(n) AS props
            LIMIT 50
            """
            with self.driver.session() as session:
                result = session.run(query, user_id=neo4j_user_id)
                return self._scan_for_encrypted(result, key)
        else:
            query = """
            MATCH (n)
            RETURN properties(n) AS props
            LIMIT 50
            """
            with self.driver.session() as session:
                result = session.run(query)
                return self._scan_for_encrypted(result, key)

    def _scan_for_encrypted(self, result, key: bytes) -> Optional[bool]:
        """Scan query records for the first encrypted field and test-decrypt it.

        Returns:
            True if a field decrypted successfully; False if a field existed but
            failed to decrypt (wrong key); None if no encrypted field was found.
        """
        for record in result:
            props = dict(record["props"])
            for field in FIELDS_TO_ENCRYPT:
                value = props.get(field)
                if isinstance(value, str) and value:
                    try:
                        decrypt_field(value, key)
                        return True  # success on first encrypted field
                    except ValueError:
                        return False  # found encrypted data but wrong key
        return None

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self.driver:
            self.driver.close()


# Global encryption service instance (lazy singleton so import never fails
# even if Neo4j is not reachable at import time).
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Return a shared EncryptionService instance (lazy singleton)."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service

