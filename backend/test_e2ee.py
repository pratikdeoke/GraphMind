"""
Standalone integration test for the E2EE crypto + re-encryption logic.

Runs WITHOUT a live Neo4j/PostgreSQL by mocking the Neo4j driver/session and
the UserService DB methods. Validates the full lifecycle:
setup -> verify-pin -> change-pin -> disable.

Run:  python test_e2ee.py
"""

import sys
import types

sys.path.insert(0, ".")

# Stub database.postgres so importing user_service (which imports it at module
# top) does NOT try to open a real PostgreSQL connection during this test.
if "database.postgres" not in sys.modules:
    _pg = types.ModuleType("database.postgres")

    class _PostgresDB:  # minimal placeholder; never used because we swap UserService
        @classmethod
        def get_cursor(cls, *a, **k):
            raise RuntimeError("DB not available in test")

    _pg.PostgresDB = _PostgresDB
    sys.modules["database.postgres"] = _pg

from services.encryption import crypto_service as cs
from services.encryption.encryption_service import EncryptionService


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeSession:
    """In-memory Neo4j-like session backed by a shared node store."""

    def __init__(self, store):
        self.store = store  # {internal_id: props_dict}

    def run(self, query, **params):
        q = " ".join(query.split())  # normalize whitespace

        if "RETURN id(n) AS node_internal_id, properties(n) AS props" in q:
            uid = params.get("user_id")
            records = [
                {"node_internal_id": nid, "props": dict(props)}
                for nid, props in self.store.items()
                if props.get("user_id") == uid
            ]
            return FakeResult(records)

        if "WHERE id(n) = $node_id" in q and "SET n = $props" in q:
            self.store[params["node_id"]] = dict(params["props"])
            return FakeResult([])

        if "RETURN properties(n) AS props" in q:
            uid = params.get("user_id")
            records = [
                {"props": dict(props)}
                for props in self.store.values()
                if uid is None or props.get("user_id") == uid
            ]
            return FakeResult(records[:50])

        return FakeResult([])


class FakeSessionCtx:
    def __init__(self, store):
        self._s = FakeSession(store)

    def __enter__(self):
        return self._s

    def __exit__(self, *args):
        return False


class FakeDriver:
    def __init__(self, store):
        self.store = store

    def session(self):
        return FakeSessionCtx(self.store)

    def verify_connectivity(self):
        return True

    def close(self):
        pass


class FakeUserService:
    """In-memory stand-in for UserService encryption metadata."""

    def __init__(self):
        self.profile = {"encryption_salt": None, "encryption_enabled": False, "encryption_hint": None}

    def get_encryption_profile(self, user_id):
        return dict(self.profile)

    def enable_encryption(self, user_id, salt, hint=None):
        self.profile.update(encryption_salt=salt, encryption_enabled=True, encryption_hint=hint)
        return True

    def update_encryption_salt(self, user_id, salt, hint=None):
        self.profile["encryption_salt"] = salt
        return True

    def disable_encryption(self, user_id):
        self.profile.update(encryption_salt=None, encryption_enabled=False, encryption_hint=None)
        return True



def main():
    UID = "user_test1"

    # --- 1. crypto primitives ---
    salt = cs.generate_salt()
    key = cs.derive_key("1234", salt)
    assert len(key) == 32
    enc = cs.encrypt_field("I spent 5000 on HDFC", key)
    assert cs.decrypt_field(enc, key) == "I spent 5000 on HDFC"
    print("[1] crypto primitives OK")

    # --- 2. setup encrypts existing plaintext nodes ---
    store = {
        1: {"id": "fact_1", "user_id": UID, "text": "I spent 5000 on HDFC", "confidence": 0.8},
        2: {"id": "txn_1", "user_id": UID, "amount": 5000, "transaction_type": "debit"},
        3: {"id": "fact_2", "user_id": "other_user", "text": "not mine"},  # isolated
    }
    svc = build_service(store)
    result = svc.setup(user_id="pg1", neo4j_user_id=UID, pin="1234", hint="my dog")
    assert result["success"] is True
    assert result["nodes_encrypted"] == 2  # only this user's 2 nodes
    assert store[1]["text"] != "I spent 5000 on HDFC"
    assert store[2]["amount"] != 5000
    assert store[3]["text"] == "not mine"  # other user untouched
    assert svc.is_enabled("pg1") is True
    print("[2] setup encrypted existing nodes OK; other users isolated")

    # --- 3. verify_pin ---
    assert svc.verify_pin("pg1", UID, "1234") is True
    assert svc.verify_pin("pg1", UID, "9999") is False
    print("[3] verify_pin correct/wrong OK")

    # --- 4. change_pin re-encrypts with new key ---
    text_before = store[1]["text"]
    ch = svc.change_pin(user_id="pg1", neo4j_user_id=UID, old_pin="1234", new_pin="5678")
    assert ch["success"] is True
    assert store[1]["text"] != text_before  # ciphertext changed
    new_key = cs.derive_key("5678", svc.get_salt("pg1"))
    assert cs.decrypt_field(store[1]["text"], new_key) == "I spent 5000 on HDFC"
    try:
        cs.decrypt_field(store[1]["text"], cs.derive_key("0000", salt))
        raise AssertionError("wrong key should not decrypt")
    except ValueError:
        pass
    print("[4] change_pin re-encrypted all nodes OK")

    try:
        svc.change_pin(user_id="pg1", neo4j_user_id=UID, old_pin="0000", new_pin="1111")
        raise AssertionError("wrong old_pin should raise")
    except ValueError:
        pass
    print("[4b] change_pin rejects wrong old PIN OK")

    # --- 5. disable decrypts back to plaintext ---
    dis = svc.disable(user_id="pg1", neo4j_user_id=UID, pin="5678")
    assert dis["success"] is True
    assert dis["nodes_decrypted"] == 2
    assert store[1]["text"] == "I spent 5000 on HDFC"
    assert store[2]["amount"] == "5000"  # stringified after round-trip
    assert svc.is_enabled("pg1") is False
    print("[5] disable decrypted everything back to plaintext OK")

    print("\nALL E2EE INTEGRATION TESTS PASSED")


def build_service(store):
    svc = EncryptionService.__new__(EncryptionService)  # bypass __init__ DB connect
    svc.driver = FakeDriver(store)
    svc.user_service = FakeUserService()
    return svc


if __name__ == "__main__":
    main()
