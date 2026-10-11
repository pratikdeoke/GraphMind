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
            
            # Add IDs to nodes if not present
            for node in extracted_data.get("nodes", []):
                if "id" not in node.get("properties", {}):
                    if "properties" not in node:
                        node["properties"] = {}
                    node["properties"]["id"] = f"{node['type'].lower()}_{uuid.uuid4().hex[:8]}"
            
            # Validate and return
            if self.validate_schema(extracted_data):
                return extracted_data
            else:
                return self._fallback_extraction(text, user_id)
                
        except Exception as e:
            print(f"Error in LLM extraction: {e}")
            return self._fallback_extraction(text, user_id)
    
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
