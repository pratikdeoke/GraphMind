"""Focused E2EE proof: inspect Neo4j ciphertext WHILE encryption is enabled."""
import base64
import json
import time
import urllib.request
from hashlib import pbkdf2_hmac

from neo4j import GraphDatabase
from config.settings import Settings

BASE = "http://localhost:8001"
EMAIL = f"e2ee_cipher_{int(time.time())}@example.com"
PASSWORD = "TestPass123!"
PIN = "424242"


def req(method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())


d = req("POST", "/auth/signup", {"email": EMAIL, "password": PASSWORD, "full_name": "Cipher"})
token = d["access_token"]
user_id = d["user_id"]
setup = req("POST", "/encryption/setup", {"pin": PIN}, token=token)
salt = setup["salt"]
print("SETUP_OK nodes_encrypted=%s" % setup["nodes_encrypted"])

key_bytes = pbkdf2_hmac("sha256", PIN.encode(), bytes.fromhex(salt), 310000, dklen=32)
b64key = base64.b64encode(key_bytes).decode()
req("POST", "/chat",
    {"message": "My locker combination is 8-4-2 and I own 120 shares of INFY",
     "user_id": "self", "retrieval_mode": "basic"},
    token=token, headers={"X-Encryption-Key": b64key})
print("CHAT_STORED")

# Neo4j user id used by the app (stored in the users table, NOT the PG UUID)
from services.database.user_service import UserService
neo_uid = UserService().get_user_by_id(user_id)["neo4j_user_id"]
s = Settings()
db = GraphDatabase.driver(s.NEO4J_URI, auth=(s.NEO4J_USER, s.NEO4J_PASSWORD))
with db.session() as ss:
    rows = list(ss.run(
        "MATCH (n {user_id: $u}) WHERE n.text IS NOT NULL "
        "RETURN labels(n) AS labels, n.text AS t, keys(n) AS keys",
        u=neo_uid))
    print("NODES_FOR_USER:", len(rows))
    from services.encryption.crypto_service import decrypt_field as _df
    enc = plain = 0
    for rec in rows:
        t = str(rec["t"])
        # Ciphertext = base64 of nonce(12)||ct||tag(16), decryptable with key.
        is_enc = False
        try:
            _df(t, key_bytes)  # raises ValueError if not our ciphertext
            is_enc = True
        except Exception:
            is_enc = False
        if is_enc:
            enc += 1
        else:
            plain += 1
        tag = "CIPHERTEXT" if is_enc else "PLAINTEXT "
        print(tag, "labels=", rec["labels"], "keys=", rec["keys"])
    print("CIPHERTEXT_FIELDS:", enc, "PLAINTEXT_FIELDS:", plain)
    can = ss.run("MATCH (c:EncryptionCanary {user_id: $u}) RETURN count(c) AS n", u=neo_uid).single()
    print("CANARY_NODES:", can["n"])
    # Show a redacted ciphertext sample (structure only)
    sample = next((str(r["t"]) for r in rows if str(r["t"]).startswith("enc:v1:")), None)
    if sample:
        parts = sample.split(":")
        print("SAMPLE_PREFIX:", parts[0] + ":" + parts[1], "| iv_len=", len(parts[2]) if len(parts) > 2 else 0)
db.close()

# Clean up: disable encryption so the demo user ends in plaintext state
req("DELETE", "/encryption/disable", None, token=token) if False else None
import urllib.error
r = urllib.request.Request(
    BASE + "/encryption/disable",
    data=json.dumps({"pin": PIN}).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    method="DELETE")
try:
    with urllib.request.urlopen(r, timeout=30) as resp:
        resp.read()
    print("DISABLED_CLEANUP_OK")
except urllib.error.HTTPError as e:
    print("DISABLE_ERR", e.code, e.read().decode()[:200])
