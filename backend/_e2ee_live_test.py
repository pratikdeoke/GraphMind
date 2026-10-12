"""End-to-end smoke test of the E2EE API flow against a LIVE backend on :8001."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8001"
EMAIL = f"e2ee_test_{int(time.time())}@example.com"
PASSWORD = "TestPass123!"
PIN = "135790"


def req(method, path, body=None, token=None, headers=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# 1. Health
s, d = req("GET", "/health")
check("health", s == 200 and d.get("status") == "healthy", str(d))

# 2. Signup
s, d = req("POST", "/auth/signup", {"email": EMAIL, "password": PASSWORD, "full_name": "E2EE Tester"})
check("signup", s in (200, 201), f"status={s} {d}")
token = d.get("access_token") or d.get("token")
check("token issued", bool(token), (token or "")[:20])

# 3. Login (get fresh token)
s, d = req("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
token2 = d.get("access_token") or d.get("token")
check("login", s == 200 and bool(token2), f"status={s}")
token = token2 or token

# 4. Encryption status BEFORE setup
s, d = req("GET", "/encryption/status", token=token)
check("status before setup", s == 200 and d.get("encryption_enabled") is False, str(d))

# 5. Setup encryption
s, d = req("POST", "/encryption/setup", {"pin": PIN, "hint": "my fav digits"}, token=token)
salt = d.get("salt")
check("setup", s == 200 and d.get("success") and bool(salt), f"status={s} salt={salt[:16] if salt else None}...")
check("setup returns 64-hex salt", bool(salt) and len(salt) == 64 and all(c in "0123456789abcdef" for c in salt), f"len={len(salt) if salt else 0}")

# 6. Status AFTER setup
s, d = req("GET", "/encryption/status", token=token)
check("status after setup", s == 200 and d.get("encryption_enabled") is True and d.get("hint") == "my fav digits", str(d))

# 7. verify-pin returns the same salt
s, d = req("POST", "/encryption/verify-pin", {"pin": PIN}, token=token)
check("verify-pin correct", s == 200 and d.get("salt") == salt and d.get("valid") is True, f"status={s}")
s, d = req("POST", "/encryption/verify-pin", {"pin": "0000"}, token=token)
check("verify-pin wrong PIN rejected", s == 401, f"status={s} {d}")

# 8. derive key locally (same params as frontend) and send via header
import base64
from hashlib import pbkdf2_hmac
key_bytes = pbkdf2_hmac("sha256", PIN.encode(), bytes.fromhex(salt), 310000, dklen=32)
b64key = base64.b64encode(key_bytes).decode()
check("local PBKDF2 key is 32 bytes", len(key_bytes) == 32, f"{len(key_bytes)} bytes")

# 9. Chat with encryption key header (memory ingest path)
s, d = req("POST", "/chat",
           {"message": "I paid 2500 rupees for groceries at BigBasket yesterday",
            "user_id": "self", "retrieval_mode": "basic"},
           token=token, headers={"X-Encryption-Key": b64key})
check("chat with X-Encryption-Key", s == 200, f"status={s} keys={list(d)[:6]}")

# 10. Chat WITHOUT the header (should still work, gracefully)
s, d = req("POST", "/chat", {"message": "hello", "user_id": "self", "retrieval_mode": "basic"}, token=token)
check("chat without header", s == 200, f"status={s}")

# 11. change-pin
s, d = req("POST", "/encryption/change-pin", {"old_pin": PIN, "new_pin": "246813"}, token=token)
check("change-pin", s == 200 and d.get("success"), f"status={s} {d}")
s, d = req("POST", "/encryption/verify-pin", {"pin": PIN}, token=token)
check("old PIN no longer valid", s == 401, f"status={s}")
s, d = req("POST", "/encryption/verify-pin", {"pin": "246813"}, token=token)
new_salt = d.get("salt")
check("new PIN valid", s == 200 and bool(new_salt), f"status={s}")
check("salt rotated on change-pin", new_salt != salt, "salt changed")

# 12. disable
s, d = req("DELETE", "/encryption/disable", {"pin": "246813"}, token=token)
check("disable", s == 200 and d.get("success"), f"status={s} {d}")
s, d = req("GET", "/encryption/status", token=token)
check("status after disable", s == 200 and d.get("encryption_enabled") is False and d.get("hint") is None, str(d))

# 13. unauthorized access blocked
s, d = req("GET", "/encryption/status")
check("status requires auth", s == 401, f"status={s}")

print("\n=== SUMMARY ===")
fails = [r for r in results if not r[1]]
print(f"{len(results) - len(fails)}/{len(results)} passed")
for n, ok, det in fails:
    print(f"  FAILED: {n} -> {det}")
