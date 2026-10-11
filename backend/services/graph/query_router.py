"""
Query router for GraphRAG-style retrieval strategies.

This module selects a retrieval strategy (basic/local/global/drift-like)
without changing the storage backend. It is designed to work with Neo4j-first
runtime retrieval and optional vector enrichment.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RetrievalStrategy(Enum):
    """High-level query strategies inspired by GraphRAG modes."""

    BASIC = "basic"
    LOCAL = "local"
    GLOBAL = "global"
    DRIFT = "drift"


@dataclass
class RetrievalPlan:
    """Execution plan selected by the query router."""

    strategy: RetrievalStrategy
    graph_depth: int
    graph_top_k: int
    vector_top_k: int
    enable_vector: bool


class QueryRouter:
    """
    Route user query to an execution strategy.

    Heuristics intentionally stay deterministic and cheap. The plan can be
    upgraded later with learned routing or LLM-assisted selection.
    """

    GLOBAL_KEYWORDS = {
        "overall",
        "summary",
        "summarize",
        "big picture",
        "across",
        "all",
        "entire",
        "portfolio review",
    }
    DRIFT_KEYWORDS = {
        "explore",
        "brainstorm",
        "what else",
        "dig deeper",
        "follow up",
        "why",
    }
    AGGREGATION_KEYWORDS = {
        "how much",
        "total",
        "sum",
        "overall amount",
        "combined",
        "in total",
    }

    def route(self, query: str, decomposed: Any = None) -> RetrievalPlan:
        """Choose retrieval strategy and execution budgets for the query."""
        query_lower = (query or "").lower()
        token_count = len(query_lower.split())

        # Prefer DRIFT for exploratory follow-up style queries.
        if any(keyword in query_lower for keyword in self.DRIFT_KEYWORDS):
            return RetrievalPlan(
                strategy=RetrievalStrategy.DRIFT,
                graph_depth=2,
                graph_top_k=24,
                vector_top_k=6,
                enable_vector=True,
            )

        # Prefer GLOBAL for broad summary-like questions.
        if any(keyword in query_lower for keyword in self.GLOBAL_KEYWORDS):
            return RetrievalPlan(
                strategy=RetrievalStrategy.GLOBAL,
                graph_depth=2,
                graph_top_k=30,
                vector_top_k=7,
                enable_vector=True,
            )

        # For numeric aggregation, graph-only is usually sufficient and faster.
        if any(keyword in query_lower for keyword in self.AGGREGATION_KEYWORDS):
            return RetrievalPlan(
                strategy=RetrievalStrategy.LOCAL,
                graph_depth=1,
                graph_top_k=24,
                vector_top_k=0,
                enable_vector=False,
            )

        # BASIC for short direct lookup queries.
        # Generous top_k: a "list my X" query must surface every distinct entity.
        # Each entity can appear as both a node and a restating Fact, so we fetch a
        # larger candidate pool and let citation-level dedup collapse duplicates.
        if token_count <= 4:
            return RetrievalPlan(
                strategy=RetrievalStrategy.BASIC,
                graph_depth=1,
                graph_top_k=24,
                vector_top_k=3,
                enable_vector=True,
            )

        # LOCAL is the default strategy for personalized Q&A.
        return RetrievalPlan(
            strategy=RetrievalStrategy.LOCAL,
            graph_depth=2,
            graph_top_k=24,
            vector_top_k=5,
            enable_vector=True,
        )
