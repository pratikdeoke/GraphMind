"""
Export classification service.

Determines how a chat answer can be exported:
- "structured": retrieved nodes are all one structured type and the answer is
  purely descriptive (no advice language) -> PDF + Excel + Copy
- "mixed": structured nodes exist, but types are mixed or the answer contains
  advice-like language -> PDF + Copy (no tabular Excel export)
- "text": no structured nodes retrieved -> Copy only
"""

from typing import Any, Dict, List

# Node types that map cleanly to tabular rows.
STRUCTURED_NODE_TYPES = [
    "Stock", "MutualFund", "Transaction", "Asset", "Portfolio", "SIP", "Goal"
]

# Phrases that indicate the answer contains personalised advice/opinions.
ADVICE_SIGNALS = [
    "recommend", "suggest", "consider", "should",
    "might want to", "advisable", "based on your",
]


def effective_node_type(node: Dict[str, Any]) -> str:
    """
    Resolve a graph/citation node to one of STRUCTURED_NODE_TYPES if possible.

    The graph stores holdings as generic "Asset" nodes carrying an
    ``asset_type`` property (stock | mutual_fund | ...). Refine those to the
    finer-grained export types "Stock"/"MutualFund" when the property allows.
    """
    node_type = str(node.get("node_type") or node.get("type") or "")
    props = node.get("properties") or {}

    if node_type == "Asset":
        asset_type = str(props.get("asset_type") or "").lower()
        if "stock" in asset_type:
            return "Stock"
        if "mutual" in asset_type or "fund" in asset_type or "sip" in asset_type:
            return "MutualFund"

    return node_type


def has_advice_signals(response_text: str) -> bool:
    """Check the answer text for advice-like phrasing."""
    text = (response_text or "").lower()
    return any(signal in text for signal in ADVICE_SIGNALS)


def classify_response(
    retrieved_nodes: List[Dict[str, Any]],
    response_text: str
) -> Dict[str, Any]:
    """
    Classify a chat response for exportability.

    Args:
        retrieved_nodes: Graph citations/nodes retrieved for the answer.
        response_text: Generated answer text.

    Returns:
        {
            "response_type": "structured" | "mixed" | "text",
            "exportable": ["pdf" | "excel" | "copy", ...],
            "has_structured_data": bool,
            "node_types": [resolved structured types present],
            "has_advice_signals": bool,
        }
    """
    structured_types = []
    for node in retrieved_nodes or []:
        resolved = effective_node_type(node)
        if resolved in STRUCTURED_NODE_TYPES and resolved not in structured_types:
            structured_types.append(resolved)

    has_structured = len(structured_types) > 0
    advice = has_advice_signals(response_text)

    if not has_structured:
        response_type = "text"
        exportable = ["copy"]
    elif len(structured_types) == 1 and not advice:
        # All structured nodes share one type and the answer is descriptive:
        # safe to render as a clean Excel table.
        response_type = "structured"
        exportable = ["pdf", "excel", "copy"]
    else:
        # Mixed node types, or advice language -> no Excel table export.
        response_type = "mixed"
        exportable = ["pdf", "copy"]

    return {
        "response_type": response_type,
        "exportable": exportable,
        "has_structured_data": has_structured,
        "node_types": structured_types,
        "has_advice_signals": advice,
    }
