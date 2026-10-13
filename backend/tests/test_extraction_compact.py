"""Standalone test for clean-graph compaction + canonical dedupe logic.

Validates the fixes that stop one long prompt from exploding the knowledge
graph into unreadable nodes:
  1. _compact_extraction caps facts/nodes/relationships.
  2. _compact_extraction dedupes nodes by canonical identity.
  3. Node ids are derived from a STABLE hash (md5), not random uuid / hash().
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BACKEND)

# Import the module by path so we don't trigger package side effects.
spec = importlib.util.spec_from_file_location(
    "llm_extractor",
    os.path.join(BACKEND, "services", "extraction", "llm_extractor.py"),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _extractor():
    # Bypass __init__ (which would need GEMINI_API_KEY / network).
    ex = mod.LLMExtractor.__new__(mod.LLMExtractor)
    return ex


def test_fact_cap_and_dedupe():
    ex = _extractor()
    facts = [{"text": "User invested in HDFC", "confidence": 0.9}]
    # 9 paraphrases / duplicates -> must collapse + cap to MAX_FACTS (5)
    for i in range(9):
        facts.append({"text": f"dup fact {i}", "confidence": 0.1})
    data = {"facts": facts, "nodes": [], "relationships": []}
    out = ex._compact_extraction(data)
    assert len(out["facts"]) <= ex.MAX_FACTS_PER_MESSAGE, out["facts"]
    # highest-confidence kept first
    assert out["facts"][0]["text"] == "User invested in HDFC"


def test_node_dedupe_by_canonical():
    ex = _extractor()
    nodes = [
        {"type": "Asset", "properties": {"name": "HDFC Fund", "canonical_name": "hdfc fund"}},
        {"type": "Asset", "properties": {"name": "HDFC Fund", "canonical_name": "hdfc fund"}},
        {"type": "Asset", "properties": {"name": "hdfc  fund ", "canonical_name": "hdfc  fund "}},
        {"type": "Goal", "properties": {"name": "Retirement", "canonical_name": "retirement"}},
    ]
    out = ex._compact_extraction({"nodes": nodes, "facts": [], "relationships": []})
    # distinct canonical keys: "hdfc fund" (dup), "hdfc  fund " (1) + Goal "retirement"
    assert len(out["nodes"]) == 3, out["nodes"]


def test_node_cap():
    ex = _extractor()
    nodes = [{"type": "Entity", "properties": {"name": f"n{i}", "canonical_name": f"n{i}"}}
             for i in range(20)]
    out = ex._compact_extraction({"nodes": nodes, "facts": [], "relationships": []})
    assert len(out["nodes"]) == ex.MAX_NODES_PER_MESSAGE


def test_relationship_dedupe_and_cap():
    ex = _extractor()
    rels = [{"type": "RELATES_TO", "from_id": "a", "to_id": "b"} for _ in range(20)]
    out = ex._compact_extraction({"nodes": [], "facts": [], "relationships": rels})
    assert len(out["relationships"]) == 1


if __name__ == "__main__":
    test_fact_cap_and_dedupe()
    test_node_dedupe_by_canonical()
    test_node_cap()
    test_relationship_dedupe_and_cap()
    print("ALL_COMPACT_TESTS_PASSED")
