"""
Export data extractor.

Builds tabular data (headers + rows) from retrieved graph nodes/citations,
using a per-node-type field map. Fields are resolved via aliases so the
extractor works with the property names actually stored in the graph
(e.g. a Transaction stores "transaction_type", the export header is "type").
"""

from typing import Any, Dict, List

from services.export.classifier import STRUCTURED_NODE_TYPES, effective_node_type

# Which fields to extract per structured node type.
FIELD_MAP: Dict[str, List[str]] = {
    "Stock": ["name", "shares", "buy_price", "current_value", "pnl"],
    "MutualFund": ["name", "monthly_sip", "units", "nav", "current_value", "returns"],
    "Transaction": ["date", "type", "asset", "amount", "notes"],
    "Asset": ["name", "asset_type", "amount_invested", "current_value"],
    "Portfolio": ["name", "value", "holdings_count"],
    "SIP": ["name", "monthly_sip", "asset", "start_date"],
    "Goal": ["name", "target_amount", "deadline", "progress"],
}

# Graph property name -> list of fallback keys tried in order.
FIELD_ALIASES: Dict[str, List[str]] = {
    "name": ["name", "label", "title"],
    "shares": ["shares", "quantity", "units_held"],
    "buy_price": ["buy_price", "purchase_price", "avg_price", "price"],
    "current_value": ["current_value", "market_value", "value"],
    "pnl": ["pnl", "profit_loss", "gain"],
    "monthly_sip": ["monthly_sip", "sip_amount", "amount"],
    "units": ["units", "units_held", "quantity"],
    "nav": ["nav", "nav_per_unit"],
    "returns": ["returns", "return_pct", "gain"],
    "date": ["date", "transaction_date", "created_at"],
    "type": ["transaction_type", "type", "txn_type"],
    "asset": ["asset", "asset_name", "name"],
    "amount": ["amount", "value"],
    "notes": ["notes", "description", "text"],
    "asset_type": ["asset_type"],
    "amount_invested": ["amount_invested", "invested", "amount"],
    "value": ["value", "current_value"],
    "holdings_count": ["holdings_count", "asset_count"],
    "start_date": ["start_date", "date", "created_at"],
    "target_amount": ["target_amount", "goal_amount", "amount"],
    "deadline": ["deadline", "target_date", "date"],
    "progress": ["progress", "progress_pct"],
}

# Columns that should render as plain numbers in exports (for summary rows).
NUMERIC_FIELDS = {
    "shares", "buy_price", "current_value", "pnl", "monthly_sip", "units",
    "nav", "returns", "amount", "amount_invested", "value", "holdings_count",
    "target_amount", "progress",
}


def _resolve_field(props: Dict[str, Any], field: str) -> Any:
    """Resolve a logical export field from node properties using aliases."""
    for key in FIELD_ALIASES.get(field, [field]):
        if key in props and props[key] not in (None, ""):
            value = props[key]
            # Coerce numeric strings ("50000", "12.5") to numbers.
            if isinstance(value, str) and field in NUMERIC_FIELDS:
                try:
                    cleaned = value.replace(",", "").replace("₹", "").strip()
                    value = float(cleaned)
                    if value.is_integer():
                        value = int(value)
                except ValueError:
                    pass
            return value
    return ""


def _iter_fact_texts(retrieved_nodes, extra_texts=None):
    texts = [str(t) for t in (extra_texts or []) if t]
    for node in retrieved_nodes or []:
        props = node.get("properties") or {}
        node_type = str(node.get("node_type") or node.get("type") or "")
        if node_type == "Fact":
            fact_text = props.get("text") or node.get("snippet") or ""
            if fact_text:
                texts.append(str(fact_text))
            continue
        folded = props.get("fact_text")
        if folded:
            if isinstance(folded, (list, tuple)):
                texts.extend(str(part) for part in folded if part)
            else:
                for part in str(folded).split("|"):
                    part = part.strip()
                    if part:
                        texts.append(part)
        snippet = node.get("snippet") or ""
        if snippet and node_type in ("Asset", "MutualFund", "Stock"):
            texts.append(str(snippet))
    return texts


def _enrich_from_fact_text(row, retrieved_nodes, extra_texts=None):
    import re
    name = str(row.get("name") or "")
    if not name:
        return
    name_re = re.escape(name)
    shares_pats = [
        re.compile(r"(\d[\d,]*(?:\.\d+)?)\s+" + name_re + r"\s+shares?", re.IGNORECASE),
        re.compile(r"(\d[\d,]*(?:\.\d+)?)\s+shares?\s+of\s+" + name_re, re.IGNORECASE),
        re.compile(name_re + r"[^\d]{0,40}?(\d[\d,]*(?:\.\d+)?)\s+shares?", re.IGNORECASE),
        re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:shares?|stocks?|units?)", re.IGNORECASE),
        re.compile(name_re + r"\s*[:\-]\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
        # Last resort: quantity directly before the name ("40 Infosys at 1380").
        re.compile(r"(\d[\d,]*(?:\.\d+)?)\s+" + name_re + r"(?![\w])", re.IGNORECASE),
    ]
    price_pats = [
        re.compile(r"(?:at|buy price|average|avg|price)[^\d]{0,12}\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
        re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:each|per share|/share)", re.IGNORECASE),
        re.compile(r"(?:Rs\.?|INR|\u20b9|\$)\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
    ]
    fact_texts = _iter_fact_texts(retrieved_nodes, extra_texts)
    for fact_text in fact_texts:
        if name.lower() not in fact_text.lower():
            continue
        if not row.get("shares"):
            for shares_pat in shares_pats:
                match = shares_pat.search(fact_text)
                if match:
                    # name-anchored patterns capture the qty in group 1
                    # except the "Apple: 10 shares" pattern (group 1 is still qty
                    # because name_re has no groups — re.escape never adds any).
                    row["shares"] = _coerce_number(match.group(1))
                    break
        if not row.get("buy_price"):
            for price_pat in price_pats:
                match = price_pat.search(fact_text)
                if match:
                    row["buy_price"] = _coerce_number(match.group(1))
                    break
        if row.get("shares") and row.get("buy_price"):
            break


def _coerce_number(raw):
    try:
        value = float(str(raw).replace(",", ""))
        return int(value) if value.is_integer() else value
    except (TypeError, ValueError):
        return ""


def extract_table(retrieved_nodes: List[Dict[str, Any]], response_text: str = "") -> Dict[str, Any]:
    """
    Extract tabular data from retrieved nodes.

    Uses the most common structured node type as the table type and only
    includes rows of that type, so the resulting table stays clean.

    Returns:
        {
            "headers": ["name", "shares", ...],
            "rows": [{"name": "Apple", "shares": 10, ...}, ...],
            "node_type": "Stock"
        }
    Returns an empty dict when no structured nodes are present.
    """
    if not retrieved_nodes:
        return {"headers": [], "rows": [], "node_type": None}

    # Count structured node types to pick the dominant one.
    type_counts: Dict[str, int] = {}
    for node in retrieved_nodes:
        resolved = effective_node_type(node)
        if resolved in STRUCTURED_NODE_TYPES:
            type_counts[resolved] = type_counts.get(resolved, 0) + 1

    if not type_counts:
        return {"headers": [], "rows": [], "node_type": None}

    node_type = max(type_counts, key=type_counts.get)
    headers = FIELD_MAP.get(node_type, ["name"])

    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for node in retrieved_nodes:
        if effective_node_type(node) != node_type:
            continue
        props = node.get("properties") or {}
        row = {field: _resolve_field(props, field) for field in headers}

        # Asset nodes don't carry amounts; recover shares/price from the
        # related Fact text when the node properties lack them.
        if node_type in ("Stock", "MutualFund"):
            _enrich_from_fact_text(
                row, retrieved_nodes, [response_text] if response_text else None)

        # Compute P&L when missing but both cost basis and value exist.
        if node_type == "Stock" and not row.get("pnl"):
            shares = row.get("shares")
            buy_price = row.get("buy_price")
            current_value = row.get("current_value")
            if isinstance(shares, (int, float)) and isinstance(buy_price, (int, float)) \
                    and isinstance(current_value, (int, float)):
                row["pnl"] = round(current_value - (shares * buy_price), 2)

        # Dedupe by identity (id or name) - a single entity may surface as
        # both an Asset node and a restating Fact.
        identity = props.get("id") or row.get("name")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        rows.append(row)

    return {"headers": headers, "rows": rows, "node_type": node_type}
