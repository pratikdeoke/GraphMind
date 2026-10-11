"""
Query Decomposition Service - Break complex queries into logical sub-components.

Optimizations:
- LLM-based decomposition for complex multi-intent queries
- Intent confidence scoring
- Entity extraction from query
- Temporal constraint detection
- Query expansion (synonyms, related concepts)
"""

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import os
import json
import re
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()


class QueryIntent(Enum):
    """Query intent types."""
    LOOKUP = "lookup"  # Simple entity lookup
    AGGREGATION = "aggregation"  # Sum, count, totals
    COMPARISON = "comparison"  # Comparative analysis
    REASONING = "reasoning"  # Multi-hop reasoning
    ALIGNMENT = "alignment"  # Goal/portfolio alignment
    TREND = "trend"  # Temporal trend analysis


@dataclass
class DecomposedQuery:
    """Represents a decomposed query with sub-components."""
    original_query: str
    primary_intent: QueryIntent
    sub_intents: List[QueryIntent]
    entities: List[Dict[str, str]]  # [{"type": "Asset", "value": "HDFC", "confidence": 0.95}]
    temporal_constraint: Optional[Tuple[datetime, datetime]]  # (start_date, end_date)
    expanded_keywords: List[str]
    decomposed_queries: List[str]  # Sub-queries if multi-intent
    confidence: float  # 0-1, how confident is the decomposition


class QueryDecomposition:
    """
    Decomposes complex queries into optimizable sub-components.
    
    Optimizations:
    - Handles multi-intent queries
    - Extracts temporal constraints
    - Identifies entities explicitly
    - Expands with synonyms
    - Suggests query execution strategy
    """
    
    # Synonym mappings for query expansion
    SYNONYMS = {
        "asset": ["holding", "investment", "stock", "mutual fund", "property", "bond"],
        "transaction": ["trade", "purchase", "sale", "buy", "sell", "invest"],
        "goal": ["target", "objective", "plan", "aspiration"],
        "aligned": ["consistent", "matching", "on-track", "supporting"],
        "portfolio": ["holdings", "assets", "investments", "allocation"],
        "return": ["gain", "profit", "yield", "interest"],
        "amount": ["quantity", "value", "cost", "price"],
    }
    
    # Intent detection patterns
    INTENT_PATTERNS = {
        QueryIntent.LOOKUP: ["what", "list", "show", "tell me", "which", "where", "find", "get"],
        QueryIntent.AGGREGATION: ["how much", "total", "sum", "count", "all", "entire", "overall", "combined"],
        QueryIntent.COMPARISON: ["compare", "vs", "versus", "difference", "which is better", "more than"],
        QueryIntent.ALIGNMENT: ["aligned", "matching", "supporting", "contributing", "progress towards"],
        QueryIntent.TREND: ["trend", "over time", "historical", "performance", "growth", "change"],
        QueryIntent.REASONING: ["why", "impact", "cause", "because", "explain", "relationship"],
    }
    
    # Temporal pattern detection
    TEMPORAL_PATTERNS = {
        "last month": timedelta(days=30),
        "last week": timedelta(days=7),
        "last year": timedelta(days=365),
        "last quarter": timedelta(days=90),
        "this month": timedelta(days=30),
        "this year": timedelta(days=365),
        "last 3 months": timedelta(days=90),
        "past 6 months": timedelta(days=180),
        "this quarter": timedelta(days=90),
        "ytd": timedelta(days=365),
    }
    
    def __init__(self):
        """Initialize LLM client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-flash-lite-latest')
        else:
            self.model = None
    
    def decompose(self, query: str) -> DecomposedQuery:
        """
        Decompose query into optimizable components.
        
        Args:
            query: User query string
            
        Returns:
            DecomposedQuery with all components extracted
        """
        query_lower = query.lower()
        
        # 1. Detect primary intent
        primary_intent = self._detect_primary_intent(query_lower)
        
        # 2. Find all intents
        sub_intents = self._detect_all_intents(query_lower)
        
        # 3. Extract entities using LLM if available
        entities = self._extract_entities(query)
        
        # 4. Extract temporal constraints
        temporal_constraint = self._extract_temporal_constraint(query_lower)
        
        # 5. Expand query with synonyms
        expanded_keywords = self._expand_query(query_lower)
        
        # 6. Generate sub-queries if multi-intent
        decomposed_queries = self._generate_subqueries(query, primary_intent, sub_intents)
        
        # 7. Calculate decomposition confidence
        confidence = self._calculate_confidence(primary_intent, entities, temporal_constraint)
        
        return DecomposedQuery(
            original_query=query,
            primary_intent=primary_intent,
            sub_intents=sub_intents,
            entities=entities,
            temporal_constraint=temporal_constraint,
            expanded_keywords=expanded_keywords,
            decomposed_queries=decomposed_queries,
            confidence=confidence
        )
    
    def _detect_primary_intent(self, query_lower: str) -> QueryIntent:
        """Detect the primary intent using pattern matching."""
        for intent, patterns in self.INTENT_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                return intent
        return QueryIntent.LOOKUP  # Default
    
    def _detect_all_intents(self, query_lower: str) -> List[QueryIntent]:
        """Detect all intents present in query."""
        detected = []
        for intent, patterns in self.INTENT_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                detected.append(intent)
        return detected if detected else [QueryIntent.LOOKUP]
    
    def _extract_entities(self, query: str) -> List[Dict[str, str]]:
        """
        Extract financial entities from query using LLM.
        
        Returns list of entities: [{"type": "Asset", "value": "HDFC", "confidence": 0.95}]
        """
        if not self.model:
            return []
        
        try:
            prompt = f"""Extract financial entities from this query. Return ONLY valid JSON.

Query: "{query}"

Return schema:
{{
    "entities": [
        {{"type": "Asset|Transaction|Goal|Metric", "value": "name", "confidence": 0.0-1.0}},
    ]
}}

Valid entity types: Asset (stocks, mutual funds, properties), Transaction (buy, sell, invest), Goal (retirement, savings), Metric (amount, return, percentage)

Only return JSON, no other text."""
            
            response = self.model.generate_content(prompt)
            result = self._parse_json_payload(response.text)
            if not isinstance(result, dict):
                return []
            return result.get("entities", [])
        except Exception as e:
            print(f"Entity extraction error: {e}")
            return []
    
    def _extract_temporal_constraint(self, query_lower: str) -> Optional[Tuple[datetime, datetime]]:
        """Extract temporal constraint from query."""
        now = datetime.now()
        
        for pattern, delta in self.TEMPORAL_PATTERNS.items():
            if pattern in query_lower:
                start_date = now - delta
                return (start_date, now)
        
        return None
    
    def _expand_query(self, query_lower: str) -> List[str]:
        """Expand query with synonyms for broader retrieval."""
        expanded = []
        
        for keyword, synonyms in self.SYNONYMS.items():
            if keyword in query_lower:
                expanded.append(keyword)
                expanded.extend(synonyms)
        
        return list(set(expanded))
    
    def _generate_subqueries(
        self, 
        query: str, 
        primary: QueryIntent, 
        sub_intents: List[QueryIntent]
    ) -> List[str]:
        """Generate sub-queries for multi-intent decomposition."""
        if len(sub_intents) <= 1:
            return [query]
        
        # For multi-intent, try LLM-based decomposition
        if not self.model:
            return [query]
        
        try:
            prompt = f"""Break this complex query into simpler sub-queries for a financial graph database.

Original Query: "{query}"
Detected Intents: {[intent.value for intent in sub_intents]}

Return ONLY a JSON list of sub-queries:
["sub_query_1", "sub_query_2", ...]

Example:
Original: "Compare my top 3 assets against my retirement goal and show what I need to do"
Decomposed: ["What are my top 3 assets?", "What is my retirement goal?", "What amount do I need to accumulate?"]
"""
            
            response = self.model.generate_content(prompt)
            queries = self._parse_json_payload(response.text)
            return queries if isinstance(queries, list) else [query]
        except Exception as e:
            print(f"Subquery generation error: {e}")
            return [query]

    def _parse_json_payload(self, text: Any) -> Any:
        """Parse JSON payloads even when wrapped in markdown/code fences."""
        if text is None:
            raise ValueError("Empty model response")

        payload = str(text).strip()
        if not payload:
            raise ValueError("Empty model response")

        # Direct parse first for clean responses.
        try:
            return json.loads(payload)
        except Exception:
            pass

        # Strip markdown code fences if present.
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", payload, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            return json.loads(fenced.group(1).strip())

        # Fallback: parse outermost JSON object/array in text.
        start_candidates = [idx for idx in [payload.find("{"), payload.find("[")] if idx != -1]
        if not start_candidates:
            raise ValueError("No JSON object found in model response")

        start = min(start_candidates)
        end_obj = payload.rfind("}")
        end_arr = payload.rfind("]")
        end = max(end_obj, end_arr)
        if end <= start:
            raise ValueError("Malformed JSON boundaries in model response")

        return json.loads(payload[start:end + 1])
    
    def _calculate_confidence(
        self,
        intent: QueryIntent,
        entities: List[Dict[str, str]],
        temporal: Optional[Tuple[datetime, datetime]]
    ) -> float:
        """Calculate confidence in decomposition."""
        confidence = 0.5  # Base confidence
        
        # Boost for entity extraction
        if entities:
            avg_entity_confidence = sum(e.get("confidence", 0) for e in entities) / len(entities)
            confidence += avg_entity_confidence * 0.3
        
        # Boost for temporal constraint
        if temporal:
            confidence += 0.2
        
        # Boost for specific intents
        if intent != QueryIntent.LOOKUP:
            confidence += 0.1
        
        return min(1.0, confidence)
