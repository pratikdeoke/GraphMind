"""Self-contained live E2E export test.
Spawns uvicorn, waits for /health, exercises /chat and /export/*, validates
PDF/XLSX bytes and populated export rows, then terminates the server.
"""
import asyncio
import json
import urllib.parse
import urllib.request
import sys
from pathlib import Path

BACKEND = Path("d:/7th sem/Project/code/GraphMind/backend")

TOKEN = (BACKEND / "test_export_token.txt").read_text(encoding="utf-8-sig").strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

BASE = "http://localhost:8001"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **HEADERS},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers, r.read()


def get(path, params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{BASE}{path}?{qs}", headers=dict(HEADERS), method="GET"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers, r.read()


async def main():
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m", "uvicorn", "api.main:app", "--port", "8001",
        cwd=str(BACKEND),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    base = "http://localhost:8001"
    for _ in range(60):
        try:
            req = urllib.request.Request(base + "/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                status, headers, body = r.status, r.headers, r.read()
            print(f"server /health -> {status}")
            break
        except Exception:
            await asyncio.sleep(1.5)
    else:
        print("server failed to start")
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            print("server stdout:", stdout.decode()[:2000])
            print("server stderr:", stderr.decode()[:2000])
        except Exception as exc:
            print("could not read server output:", exc)
        return

    uid = "afdc1e46-e6b6-46ea-bd97-eef6dd09fa99"
    chat_payload = {
        "user_id": uid,
        "message": "What stocks do I own?",
    }
    status, headers, body = await asyncio.to_thread(post, "/chat", chat_payload)
    chat = json.loads(body)
    print(f"POST /chat -> {status} response_type={chat.get('response_type')} "
          f"exportable={chat.get('exportable')}")
    export_data = chat.get("export_data") or {}
    print(f"export node_type={export_data.get('node_type')} "
          f"headers={export_data.get('headers')} rows={len(export_data.get('rows', []))}")
    rows = export_data.get("rows", [])
    print("rows:")
    for r in rows:
        print("  ", json.dumps(r, ensure_ascii=False).replace("\n", ""))

    # Validate the extractor pipeline used by the live path. shares/buy_price
    # are recovered from Fact text; current_value/pnl stay empty when the
    # graph genuinely stores no market value for the asset (as with this
    # fixture user — confirmed by direct Neo4j inspection).
    ok = bool(rows) and all(
        r.get(f) not in (None, "")
        for r in rows
        for f in ("shares", "buy_price")
    )
    print("enrichment populated shares/buy_price:", ok)

    # Regenerate/verify PDF/Excel bytes for the chat response.
    for fmt in ("pdf", "excel"):
        status, headers, body = await asyncio.to_thread(
            post,
            "/export/response",
            {"user_id": uid, "response_text": "You own 2 stocks.", "format": fmt},
        )
        ctype = headers.get("content-type", "")
        cdisp = headers.get("content-disposition", "")
        suffix = b"%PDF-" if fmt == "pdf" else b"PK\x03\x04"
        print(
            f"POST /export/response fmt={fmt} -> {status} "
            f"ctype={ctype.split(';')[0]} bytes={len(body)} "
            f"magic={body[:4]!r} cdisp={cdisp!r}"
        )
        assert status == 200
        assert suffix in body
        assert "attachment" in cdisp
        ext = "pdf" if fmt == "pdf" else "xlsx"
        (BACKEND / f"export_live_{fmt}.{ext}").write_bytes(body)

    # Full memory export (PDF bytes). /export/memory is a GET endpoint.
    status, headers, body = await asyncio.to_thread(
        get, "/export/memory", {"format": "pdf"}
    )
    print(f"GET /export/memory pdf -> {status} bytes={len(body)} "
          f"magic={body[:4]!r}")
    assert status == 200 and b"%PDF-" in body
    (BACKEND / "export_live_memory.pdf").write_bytes(body)

    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()

    print("LIVE E2E PASSED" if ok else "LIVE E2E FAILED")


if __name__ == "__main__":
    asyncio.run(main())
