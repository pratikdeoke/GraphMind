"""
LLM Extractor - Converts user text to structured graph format.

Input: Raw user text
Output: Structured JSON with nodes and relationships

Example Output:
{
    "nodes": [
        {
            "type": "Asset",
            "properties": {
                "name": "HDFC Mutual Fund",
                "value": 50000,
                "asset_type": "mutual_fund"
            }
        }
    ],
    "relationships": [
        {
            "type": "OWNS",
            "from_node": "User",
            "to_node": "Asset",
            "properties": {
                "acquired_date": "2026-02-21"
            }
        }
    ]
}
"""

from typing import Dict, List, Any
import os
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()


class LLMExtractor:
    """
    LLM-based entity and relationship extractor.
    """
    
    def __init__(self):
        """Initialize the LLM extractor."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-flash-lite-latest')
        else:
            self.model = None
    
    MAX_FACTS_PER_MESSAGE = 5
    MAX_NODES_PER_MESSAGE = 6
    MAX_RELS_PER_MESSAGE = 8

    def extract(self, text: str, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract structured entities and relationships from text.
        
        Args:
            text: User input text
            user_id: User identifier for context
            
        Returns:
            Dictionary with 'nodes' and 'relationships' lists
        """
        if not self.model:
            return self._fallback_extraction(text, user_id)
        
        try:
            prompt = self._build_extraction_prompt(text)
            response = self.model.generate_content(prompt)
            
            # Parse JSON response
            response_text = response.text.strip()
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            extracted_data = json.loads(response_text)
            
            # Ensure all required keys exist
            if "facts" not in extracted_data:
                extracted_data["facts"] = []
            if "nodes" not in extracted_data:
                extracted_data["nodes"] = []
            if "relationships" not in extracted_data:
                extracted_data["relationships"] = []

            # Add IDs + canonical names to nodes if not present.
            # Materialize canonical identity BEFORE compaction so node dedup in
            # _compact_extraction can key on canonical_name (not random id).
            for node in extracted_data.get("nodes", []):
                if "properties" not in node:
                    node["properties"] = {}
                props = node["properties"]
                if "id" not in props:
                    props["id"] = f"{node['type'].lower()}_{uuid.uuid4().hex[:8]}"
                # Canonical identity used for MERGE dedupe in ingestion.
                # LLM may already provide normalized_name; always materialize
                # canonical_name so ingestion can MERGE on it.
                raw_name = props.get("name") or props.get("normalized_name") or ""
                if raw_name and "canonical_name" not in props:
                    props["canonical_name"] = str(raw_name).strip().lower()
                if props.get("normalized_name") and "canonical_name" not in props:
                    props["canonical_name"] = str(props["normalized_name"]).strip().lower()

            # Clean-graph caps: keep viz understandable even for 100-line prompts.
            # Keep highest-confidence items, drop the long tail.
            extracted_data = self._compact_extraction(extracted_data)
            
            # Validate and return
            if self.validate_schema(extracted_data):
                return extracted_data
            else:
                return self._fallback_extraction(text, user_id)
                
        except Exception as e:
            print(f"Error in LLM extraction: {e}")
            return self._fallback_extraction(text, user_id)

    def _compact_extraction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Cap extraction size and drop duplicates so the knowledge graph
        stays clean and visualizable even for very long prompts.

        Rules:
        - Facts: dedupe by normalized text, keep highest-confidence, cap at
          MAX_FACTS_PER_MESSAGE.
        - Nodes: dedupe by canonical identity (label + canonical_name/id),
          keep first occurrence, cap at MAX_NODES_PER_MESSAGE.
        - Relationships: dedupe by (type, from, to), cap at MAX_RELS_PER_MESSAGE.
        """
        def _conf(item: Dict[str, Any]) -> float:
            try:
                return float(item.get("confidence", 0.8) or 0.8)
            except (TypeError, ValueError):
                return 0.8

        facts = [f for f in data.get("facts", []) if isinstance(f, dict) and f.get("text")]
        seen_facts = set()
        uniq_facts = []
        for f in facts:
            key = str(f["text"]).strip().lower()
            if key and key not in seen_facts:
                seen_facts.add(key)
                uniq_facts.append(f)
        uniq_facts.sort(key=_conf, reverse=True)
        data["facts"] = uniq_facts[: self.MAX_FACTS_PER_MESSAGE]

        nodes = [n for n in data.get("nodes", []) if isinstance(n, dict)]
        seen_nodes = set()
        uniq_nodes = []
        for n in nodes:
            props = n.get("properties", {}) or {}
            ident = (
                str(props.get("canonical_name") or props.get("normalized_name")
                    or props.get("id") or props.get("name") or "")
                .strip().lower()
            )
            key = (n.get("type"), ident)
            if key in seen_nodes:
                continue
            seen_nodes.add(key)
            uniq_nodes.append(n)
        data["nodes"] = uniq_nodes[: self.MAX_NODES_PER_MESSAGE]

        rels = [r for r in data.get("relationships", []) if isinstance(r, dict)]
        seen_rels = set()
        uniq_rels = []
        for r in rels:
            key = (
                r.get("type"),
                r.get("from_id") or r.get("from_name") or r.get("from_type"),
                r.get("to_id") or r.get("to_name") or r.get("to_type"),
            )
            if key in seen_rels:
                continue
            seen_rels.add(key)
            uniq_rels.append(r)
        data["relationships"] = uniq_rels[: self.MAX_RELS_PER_MESSAGE]

        return data

    def _build_extraction_prompt(self, text: str) -> str:
        """Build the extraction prompt for LLM."""
        return """You are a deterministic memory extraction engine for a user-scoped personal knowledge graph.

Your task is to extract structured nodes, atomic facts, preferences, and relationships from a single user message.

You MUST:
- Extract only information explicitly present in the message
- Create atomic facts (one fact per distinct piece of information)
- Never invent data not present in text
- Return STRICTLY valid JSON
- Return NO explanation text
- Return NO markdown
- Return NO comments

HARD LIMITS (never exceed, even for very long input):
- At most 5 facts
- At most 6 nodes total
- At most 8 relationships
If the message contains more information than these limits allow, keep only
the most important/salient items and merge the rest into the facts you keep.
DO NOT list every minor detail.

------------------------------------------------------------
ENTITY TYPES (use only these exact types)

Core Types:
- Asset
- Goal
- Transaction
- RiskProfile
- Entity
- Event
- Preference
- Fact

------------------------------------------------------------
RELATIONSHIP TYPES (use only these exact types)

- OWNS
- HAS_GOAL
- MADE_TRANSACTION
- AFFECTS_ASSET
- CONTRIBUTES_TO
- HAS_RISK
- RELATES_TO
- CONFIRMS
- PREFERS
- PARTICIPATES_IN
- DERIVED_FROM

------------------------------------------------------------
EXTRACTION RULES

1. FACTS (CRITICAL: Minimal & Non-Redundant)
**IMPORTANT**: Create only ONE atomic fact per distinct event/statement.
- Do NOT paraphrase or restate the same information.
- Do NOT create overlapping facts.
- Facts are natural language summaries of structured data.
- Structured nodes (Transaction, Asset, Goal) are ground truth.
- Facts provide linguistic context, not duplicate data.

Examples:
"I invested 50,000 in HDFC."
→ Fact 1: "User invested 50000 in HDFC Mutual Fund."  (ONE FACT ONLY)

❌ BAD (redundant):
→ "User invested 50000"
→ "Investment was made in HDFC"  
→ "Amount is 50000"

✅ GOOD (atomic):
→ "User invested 50000 in HDFC Mutual Fund."

2. ASSETS
Extract if user mentions:
- Stocks
- Mutual funds
- Bonds
- Real estate
- Gold
- Crypto
- Any financial holding

**CRITICAL**: Asset is an ENTITY, not an event.
Do NOT store amounts on Asset.
Amounts belong to Transaction only.

**NAMING RULES**:
- Keep FULL entity name ("HDFC Mutual Fund", not "HDFC")
- Add normalized_name for deduplication (lowercase, underscores)

Include properties:
{{
  "name": "string (FULL name, preserve original)",
  "normalized_name": "string (lowercase_with_underscores for matching)",
  "asset_type": "stock | mutual_fund | bond | real_estate | gold | crypto | other"
}}

Example:
"hdfc mutual fund" → {{"name": "HDFC Mutual Fund", "normalized_name": "hdfc_mutual_fund", "asset_type": "mutual_fund"}}

If current value is explicitly stated ("worth X now"):
{{
  "name": "string",
  "asset_type": "...",
  "current_value": number (only if explicitly mentioned as current worth)
}}

Note:
- Do NOT extract amount_invested - that goes in Transaction.amount
- Convert numeric values to plain numbers (₹50,000 → 50000)

3. GOALS
Extract financial goals such as:
- Retirement
- Education
- House purchase
- Emergency fund
- Travel
- Savings target

Properties:
{{
  "name": "string",
  "target_amount": number (if mentioned),
  "target_year": number (if mentioned)
}}

4. TRANSACTIONS (Ground Truth for Events)
Extract when user:
- Invested
- Withdrew
- Deposited
- Transferred
- Sold
- Bought

**CRITICAL**: Amount ALWAYS goes on Transaction, never on Asset.

Required Properties:
{{
  "amount": number (required for any transaction),
  "transaction_type": "investment | withdrawal | deposit | transfer | buy | sell",
  "date": "ISO date string if mentioned, otherwise omit"
}}

Example:
"I invested 50000 in HDFC"
→ Transaction: {{amount: 50000, transaction_type: "investment"}}
→ Asset: {{name: "HDFC", asset_type: "mutual_fund"}} (NO amount here!)

5. RISK PROFILE
Extract if user expresses risk tolerance.
Allowed values:
- low
- moderate
- high
- aggressive

6. PREFERENCES
Extract when user expresses:
- "I prefer"
- "I like"
- "I avoid"
- "I don't like"
- "I want to focus on"

Properties:
{{
  "text": "exact preference statement"
}}

7. GENERIC ENTITY
Extract:
- People
- Organizations
- Places
- Concepts
- Companies

Properties:
{{
  "name": "string"
}}

8. EVENTS
Extract time-based commitments or milestones.
Properties:
{{
  "name": "string",
  "date": "ISO date if available"
}}

9. RELATIONSHIPS (Canonical Memory Pattern)

**CRITICAL STRUCTURE**:
For investments/transactions, create this pattern:
1. (User)-[:MADE_TRANSACTION]->(Transaction)
2. (Transaction)-[:AFFECTS_ASSET]->(Asset)
3. (Fact)-[:CONFIRMS]->(Transaction)

This ensures Transaction + Asset are ground truth.
Facts provide linguistic support.

Standard Relationships:
- MADE_TRANSACTION (User → Transaction) - user performs transaction
- AFFECTS_ASSET (Transaction → Asset) - transaction affects an asset
- CONFIRMS (Fact → Transaction/Asset/Goal) - fact confirms structured data
- OWNS (User → Asset) - direct ownership (for non-transaction assets)
- HAS_GOAL (User → Goal)
- CONTRIBUTES_TO (Asset → Goal)
- HAS_RISK (Asset → RiskProfile)
- RELATES_TO (Fact → Entity) - for generic facts
- PREFERS (User → Preference)
- PARTICIPATES_IN (User → Event)

Always set:
"from_type"
"to_type"
"from_name"
"to_name"

Use "user" as the User node name.

10. CONTRADICTIONS
If the message clearly corrects previous information (e.g. "Actually it was 40000, not 50000"):
- Extract new Fact
- Do NOT invent contradiction edge here
- Just extract the corrected fact

Contradiction resolution is handled downstream.

------------------------------------------------------------
STRICT OUTPUT FORMAT

Return ONLY this JSON structure:

{{
  "facts": [
    {{
      "text": "Atomic fact",
      "confidence": 0.85
    }}
  ],
  "nodes": [
    {{
      "type": "Asset",
      "properties": {{
        "name": "HDFC",
        "asset_type": "mutual_fund",
        "amount_invested": 50000
      }}
    }}
  ],
  "relationships": [
    {{
      "type": "OWNS",
      "from_type": "User",
      "to_type": "Asset",
      "from_name": "user",
      "to_name": "HDFC",
      "properties": {{}}
    }}
  ]
}}

If nothing extractable:
Return:
{{
  "facts": [],
  "nodes": [],
  "relationships": []
}}

------------------------------------------------------------
INPUT MESSAGE:
"{}"

Return JSON now.""".format(text)
    
    def _fallback_extraction(self, text: str, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Fallback simple keyword-based extraction."""
        nodes = []
        relationships = []
        
        text_lower = text.lower()
        
        # Simple pattern matching for investments
        if any(word in text_lower for word in ["invested", "bought", "purchased"]):
            # Try to extract asset name and amount
            words = text.split()
            for i, word in enumerate(words):
                if word.lower() in ["in", "into"] and i + 1 < len(words):
                    asset_name = " ".join(words[i+1:i+4])  # Next 3 words as asset name
                    
                    # Try to find amount
                    for w in words:
                        if w.replace(",", "").replace(".", "").isdigit():
                            amount = float(w.replace(",", ""))
                            
                            asset_id = f"asset_{uuid.uuid4().hex[:8]}"
                            nodes.append({
                                "type": "Asset",
                                "properties": {
                                    "id": asset_id,
                                    "name": asset_name.strip(),
                                    "current_value": amount,
                                    "asset_type": "investment"
                                }
                            })
                            
                            relationships.append({
                                "type": "OWNS",
                                "from_type": "User",
                                "to_type": "Asset",
                                "from_name": "user",
                                "to_name": asset_name.strip(),
                                "properties": {
                                    "acquired_date": datetime.now().strftime("%Y-%m-%d")
                                }
                            })
                            break
                    break
        
        return {
            "facts": [],  # Fallback has no facts
            "nodes": nodes,
            "relationships": relationships
        }
    
    def validate_schema(self, extracted_data: Dict[str, Any]) -> bool:
        """
        Validate that extracted data matches expected schema.
        
        Args:
            extracted_data: Extracted nodes and relationships
            
        Returns:
            True if valid, False otherwise
        """
        if not isinstance(extracted_data, dict):
            return False
        
        # Check all required keys exist
        if "facts" not in extracted_data:
            return False
        if "nodes" not in extracted_data:
            return False
        if "relationships" not in extracted_data:
            return False
        
        # Validate facts
        for fact in extracted_data.get("facts", []):
            if not isinstance(fact, dict) or "text" not in fact:
                return False
        
        # Validate nodes
        for node in extracted_data.get("nodes", []):
            if "type" not in node or "properties" not in node:
                return False
        
        # Validate relationships
        for rel in extracted_data.get("relationships", []):
            if "type" not in rel:
                return False
        
        return True
