"""
Query Understanding - Intent classification and entity extraction for retrieval.

Classifies queries into retrieval modes:
- DIRECT_LOOKUP: Simple entity queries
- RELATIONAL_REASONING: Multi-hop reasoning
- AGGREGATION: Sum, count, total queries
"""

from typing import Tuple, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import re


class RetrievalMode(Enum):
    """Query retrieval modes."""
    DIRECT_LOOKUP = "direct_lookup"
    RELATIONAL_REASONING = "relational_reasoning"
    AGGREGATION = "aggregation"


class QueryUnderstanding:
    """
    Lightweight query understanding without heavy LLM.

    Uses deterministic rules for intent classification.
    """

    # Keywords for each mode
    AGGREGATION_KEYWORDS = [
        "how much", "total", "sum", "count", "all", "entire",
        "overall", "calculate", "add up", "combined"
    ]

    RELATIONAL_KEYWORDS = [
        "why", "compare", "aligned", "relationship", "between",
        "impact", "affect", "contributing", "towards", "goal",
        "progress", "performance", "vs", "versus"
    ]

    DIRECT_LOOKUP_KEYWORDS = [
        "what", "list", "show", "tell me", "which", "where",
        "who", "when", "find", "get"
    ]

    # Timeline keywords
    TIMELINE_PATTERNS = {
        "last month": timedelta(days=30),
        "last week": timedelta(days=7),
        "last year": timedelta(days=365),
        "recent": timedelta(days=7),
        "this month": timedelta(days=30),
        "this year": timedelta(days=365),
        "today": timedelta(days=1),
        "yesterday": timedelta(days=2),
    }

    @staticmethod
    def classify_query(query: str) -> Tuple[RetrievalMode, int]:
        """
        Classify query into retrieval mode.

        Args:
            query: User's query text

        Returns:
            Tuple of (mode, recommended_depth)
        """
        query_lower = query.lower()

        # Check aggregation first (most specific)
        if any(kw in query_lower for kw in QueryUnderstanding.AGGREGATION_KEYWORDS):
            return RetrievalMode.AGGREGATION, 2

        # Check relational reasoning
        if any(kw in query_lower for kw in QueryUnderstanding.RELATIONAL_KEYWORDS):
            return RetrievalMode.RELATIONAL_REASONING, 3

        # Default to direct lookup
        return RetrievalMode.DIRECT_LOOKUP, 2

    @staticmethod
    def extract_timeline(query: str) -> Optional[datetime]:
        """
        Extract timeline filter from query.

        Args:
            query: User's query text

        Returns:
            Start datetime if timeline mentioned, None otherwise
        """
        query_lower = query.lower()

        for pattern, delta in QueryUnderstanding.TIMELINE_PATTERNS.items():
            if pattern in query_lower:
                return datetime.now() - delta

        # Check for specific dates (e.g., "in 2024", "since January")
        year_match = re.search(r'\b(20\d{2})\b', query)
        if year_match:
            year = int(year_match.group(1))
            return datetime(year, 1, 1)

        return None

    @staticmethod
    def extract_entity_mentions(query: str, known_entities: List[str]) -> List[str]:
        """
        Extract entity mentions from query.

        Args:
            query: User's query text
            known_entities: List of known entity names from graph

        Returns:
            List of matched entity names
        """
        query_lower = query.lower()
        mentioned = []

        for entity in known_entities:
            if entity.lower() in query_lower:
                mentioned.append(entity)

        return mentioned

    @staticmethod
    def extract_query_keywords(query: str) -> List[str]:
        """
        Extract important keywords from query for filtering.

        Args:
            query: User's query text

        Returns:
            List of significant keywords (nouns, verbs, entities)
        """
        # Remove common stop words
        stop_words = {
            'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
            'what', 'which', 'where', 'when', 'why', 'how', 'do', 'did', 'does',
            'in', 'on', 'at', 'to', 'for', 'from', 'by', 'with', 'about',
            'have', 'has', 'had', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'my', 'your', 'his', 'her', 'its', 'our', 'their'
        }

        words = re.findall(r'\b[a-z]+\b', query.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return list(set(keywords))  # Remove duplicates

    @staticmethod
    def needs_vector_search(query: str) -> bool:
        """
        Determine if query needs vector search for fuzzy matching.

        Args:
            query: User's query text

        Returns:
            True if vector search recommended
        """
        fuzzy_keywords = [
            "about", "related to", "similar", "like",
            "stuff", "things", "something about"
        ]

        query_lower = query.lower()
        return any(kw in query_lower for kw in fuzzy_keywords)
