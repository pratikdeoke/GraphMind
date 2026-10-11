"""Smoke test for the export feature (classifier, extractor, generators)."""
import sys

from services.export.classifier import classify_response, effective_node_type
from services.export.extractor import extract_table
from services.export.generators import (
    export_filename,
    generate_memory_excel,
    generate_memory_pdf,
    generate_response_excel,
    generate_response_pdf,
)

failures = []


def check(name, cond, detail=""):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── classifier ──
stock_nodes = [
    {"node_type": "Asset", "properties": {"name": "Apple", "asset_type": "stock", "shares": 10, "buy_price": 150, "current_value": 1750}},
    {"node_type": "Asset", "properties": {"name": "Tata Motors", "asset_type": "stock", "shares": 5, "buy_price": 400, "current_value": 2100}},
    {"node_type": "Fact", "properties": {"text": "User holds 10 shares of Apple"}},
]
mixed_nodes = stock_nodes + [
    {"node_type": "Asset", "properties": {"name": "HDFC MF", "asset_type": "mutual_fund", "monthly_sip": 5000}},
]
text_nodes = [{"node_type": "Fact", "properties": {"text": "User prefers safe investments"}}]

r = classify_response(stock_nodes, "You own 2 stocks.")
check("structured classification", r["response_type"] == "structured" and r["exportable"] == ["pdf", "excel", "copy"], str(r))

r = classify_response(mixed_nodes, "Here is your portfolio.")
check("mixed classification (mixed types)", r["response_type"] == "mixed" and r["exportable"] == ["pdf", "copy"], str(r))

r = classify_response(stock_nodes, "I recommend you consider buying more bonds, based on your profile.")
check("mixed classification (advice)", r["response_type"] == "mixed" and "excel" not in r["exportable"], str(r))

r = classify_response(text_nodes, "You seem risk-averse.")
check("text classification", r["response_type"] == "text" and r["exportable"] == ["copy"], str(r))

r = classify_response([], "")
check("empty classification", r["response_type"] == "text", str(r))

check("effective type refinement", effective_node_type({"node_type": "Asset", "properties": {"asset_type": "mutual_fund"}}) == "MutualFund")

# ── extractor ──
table = extract_table(stock_nodes)
check("extract_table headers", table["headers"] == ["name", "shares", "buy_price", "current_value", "pnl"], str(table["headers"]))
check("extract_table node_type", table["node_type"] == "Stock")
check("extract_table rows (facts excluded)", len(table["rows"]) == 2, str(len(table["rows"])))
check("extract_table row values", table["rows"][0]["name"] == "Apple" and table["rows"][0]["shares"] == 10)
check("extract_table pnl computed", table["rows"][0]["pnl"] == 250, str(table["rows"][0]))

txn_nodes = [
    {"node_type": "Transaction", "properties": {"transaction_type": "buy", "amount": 50000, "date": "2024-01-15", "asset": "HDFC MF"}},
]
table = extract_table(txn_nodes)
check("transaction headers", table["headers"] == ["date", "type", "asset", "amount", "notes"], str(table["headers"]))
check("transaction alias mapping", table["rows"][0]["type"] == "buy" and table["rows"][0]["amount"] == 50000)

check("extract empty", extract_table([])["node_type"] is None)

# ── fact-text enrichment ──
enrich_nodes = [
    {"node_type": "Asset", "properties": {"name": "Apple", "asset_type": "stock"}},
    {"node_type": "Asset", "properties": {"name": "Tata Motors", "asset_type": "stock"}},
    {"node_type": "Fact", "properties": {"text": "User bought 10 shares of Apple at 150 each."}},
    {"node_type": "Fact", "properties": {"text": "User bought 5 shares of Tata Motors at 400 each for a total of 2000."}},
]
table = extract_table(enrich_nodes)
rows = {r["name"]: r for r in table["rows"]}
check("enrich shares", rows["Apple"]["shares"] == 10 and rows["Tata Motors"]["shares"] == 5, str(rows))
check("enrich buy_price", rows["Apple"]["buy_price"] == 150 and rows["Tata Motors"]["buy_price"] == 400, str(rows))

enrich_nodes2 = [
    {"node_type": "Asset", "properties": {"name": "HDFC Bank", "asset_type": "stock"}},
    {"node_type": "Fact", "properties": {"text": "User holds 20 shares of HDFC Bank at an average buy price of ₹1600."}},
]
table = extract_table(enrich_nodes2)
check("enrich buy price phrase", table["rows"][0]["buy_price"] == 1600 and table["rows"][0]["shares"] == 20, str(table["rows"]))

# ── dedup fold + enrichment (what the retrieval pipeline now returns) ──
# An Asset node (amounts not stored on entity nodes) plus a Fact that restates it;
# extract_table must fill in the amounts from the Fact text.
asset_only_nodes = [
    {"node_type": "Asset", "entity_type": "stock",
     "properties": {"id": "asset_a1", "name": "Apple", "asset_type": "stock"}},
    {"node_type": "Fact",
     "properties": {"text": "User bought 10 shares of Apple at 150 each."}},
]
table = extract_table(asset_only_nodes)
rows = {r["name"]: r for r in table["rows"]}
check("dedup-fold: Apple shares", rows["Apple"]["shares"] == 10,
      str(rows["Apple"]))
check("dedup-fold: Apple buy_price", rows["Apple"]["buy_price"] == 150,
      str(rows["Apple"]))
check("dedup-fold: no empty columns",
      all(rows["Apple"].get(f) not in (None, "")
          for f in ("shares", "buy_price")), str(rows["Apple"]))

# ── generators ──
export_data = extract_table(stock_nodes)
pdf = generate_response_pdf(
    response_text="You own 2 stocks.\nApple and Tata Motors.",
    export_data=export_data,
    title="Stock Holdings",
    user_name="Pratik",
)
check("response PDF bytes", pdf[:5] == b"%PDF-", pdf[:20].hex())

xlsx = generate_response_excel(export_data)
check("response Excel bytes", xlsx[:2] == b"PK", xlsx[:4].hex())

mem_pdf = generate_memory_pdf([
    {"heading": "Stock Holdings", "headers": ["name", "shares"],
     "rows": [["Apple", 10], ["Tata Motors", 5]]},
    {"heading": "Chat History", "headers": ["date", "role", "message"],
     "rows": [["2026-11-10 10:00", "user", "Hello"]]},
], user_name="Pratik")
check("memory PDF bytes", mem_pdf[:5] == b"%PDF-")

mem_xlsx = generate_memory_excel([
    {"title": "Stock Holdings", "headers": ["name", "shares"], "rows": [["Apple", 10]]},
    {"title": "Transactions", "headers": ["date", "amount"], "rows": [["2024-01-01", 500]]},
])
check("memory Excel bytes", mem_xlsx[:2] == b"PK")

check("filename format", export_filename("pdf").startswith("graphmind_export_") and export_filename("pdf").endswith(".pdf"), export_filename("pdf"))

# ── full app import (routers wire up) ──
try:
    from api.main import app
    paths = set(app.openapi()["paths"].keys())
    check("route /export/response registered", "/export/response" in paths, str(sorted(p for p in paths if "export" in p)))
    check("route /export/memory registered", "/export/memory" in paths)
except Exception as exc:
    check("app import", False, str(exc))

# ── chat route helper ──
try:
    from api.routes.chat import build_export_fields
    fields = build_export_fields(stock_nodes, "You own 2 stocks.")
    check("chat export fields", fields["response_type"] == "structured" and fields["export_data"]["node_type"] == "Stock", str(fields))
    fields = build_export_fields(None, None)
    check("chat export fields fallback", fields == {"response_type": "text", "exportable": ["copy"], "export_data": None}, str(fields))
except Exception as exc:
    check("chat helper import", False, str(exc))

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL TESTS PASSED")
