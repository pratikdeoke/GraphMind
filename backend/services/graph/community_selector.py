"""
Dynamic community selection for global retrieval mode.

This module builds lightweight communities from retrieved context and ranks them
for map-reduce style synthesis.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, List, Tuple
import re


@dataclass
class CommunityCandidate:
    """A candidate community built from retrieved memories."""

    id: str
    title: str
    graph_items: List[Dict[str, Any]]
    vector_items: List[Dict[str, Any]]
    score: float
    score_breakdown: Dict[str, float]


class DynamicCommunitySelector:
    """Build and rank communities for global query handling."""

    STOP_WORDS = {
        "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with",
        "is", "are", "was", "were", "my", "your", "our", "their", "what", "how",
        "when", "where", "why", "which", "show", "tell", "about", "all", "overall",
    }

    def select(
        self,
        query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> Tuple[List[CommunityCandidate], float]:
        """Return top communities and elapsed selection ms."""
        start = datetime.now(timezone.utc)
        communities = self._build_communities(graph_context, vector_context)

        if not communities:
            return [], 0.0

        query_tokens = self._tokens(query)
        for community in communities:
            semantic_score = self._semantic_score(query_tokens, community)
            centrality_score = self._centrality_score(community)
            recency_score = self._recency_score(community)

            final_score = (
                0.50 * semantic_score +
                0.35 * centrality_score +
                0.15 * recency_score
            )
            community.score = round(final_score, 4)
            community.score_breakdown = {
                "semantic": round(semantic_score, 4),
                "centrality": round(centrality_score, 4),
                "recency": round(recency_score, 4),
            }

        communities.sort(key=lambda c: c.score, reverse=True)
        selected = communities[:max(1, top_k)]

        elapsed_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return selected, elapsed_ms

    def _build_communities(
        self,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]],
    ) -> List[CommunityCandidate]:
        """Build lightweight communities grouped by key memory anchors."""
        grouped: Dict[str, Dict[str, Any]] = {}

        for node in graph_context:
            if not isinstance(node, dict):
                continue
            node_type = node.get("type", "Entity")
            props = node.get("properties", {}) or {}
            anchor = props.get("name") or props.get("normalized_name") or node_type
            key = f"{node_type}:{str(anchor).lower()}"
            if key not in grouped:
                grouped[key] = {
                    "title": f"{node_type} - {anchor}",
                    "graph": [],
                    "vector": [],
                }
            grouped[key]["graph"].append(node)

        # Attach vector entries to the closest community using token overlap.
        for chunk in vector_context:
            if not isinstance(chunk, dict):
                continue
            chunk_text = (chunk.get("text") or "").strip()
            if not chunk_text:
                continue

            best_key = None
            best_overlap = 0.0
            chunk_tokens = self._tokens(chunk_text)
            for key, data in grouped.items():
                title_tokens = self._tokens(data["title"])
                denom = max(1, min(len(chunk_tokens), len(title_tokens)))
                overlap = len(chunk_tokens & title_tokens) / denom
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_key = key

            if best_key is None:
                best_key = "misc:memory"
                if best_key not in grouped:
                    grouped[best_key] = {
                        "title": "Memory - Miscellaneous",
                        "graph": [],
                        "vector": [],
                    }

            grouped[best_key]["vector"].append(chunk)

        communities: List[CommunityCandidate] = []
        for idx, (_, data) in enumerate(grouped.items(), start=1):
            communities.append(
                CommunityCandidate(
                    id=f"community_{idx}",
                    title=data["title"],
                    graph_items=data["graph"],
                    vector_items=data["vector"],
                    score=0.0,
                    score_breakdown={},
                )
            )
        return communities

    def _semantic_score(self, query_tokens: set[str], community: CommunityCandidate) -> float:
        """Lexical overlap between query and community textual footprint."""
        blob = [community.title]
        for node in community.graph_items:
            props = node.get("properties", {}) if isinstance(node, dict) else {}
            blob.append(str(props.get("name", "")))
            blob.append(str(props.get("text", "")))
            blob.append(str(node.get("snippet", "")))
        for chunk in community.vector_items:
            blob.append(str(chunk.get("text", ""))[:240])

        tokens = self._tokens(" ".join(blob))
        if not query_tokens or not tokens:
            return 0.0
        denom = max(1, min(len(query_tokens), len(tokens)))
        return min(1.0, len(query_tokens & tokens) / denom)

    def _centrality_score(self, community: CommunityCandidate) -> float:
        """Average retrieval confidence signal across community items."""
        scores: List[float] = []
        for node in community.graph_items:
            if not isinstance(node, dict):
                continue
            scores.append(float(node.get("retrieval_score", 0.5)))
        for chunk in community.vector_items:
            if not isinstance(chunk, dict):
                continue
            scores.append(float(chunk.get("retrieval_score", chunk.get("similarity", 0.5))))
        if not scores:
            return 0.0
        return min(1.0, max(0.0, sum(scores) / len(scores)))

    def _recency_score(self, community: CommunityCandidate) -> float:
        """Exponential decay based on most recent timestamp in community."""
        now = datetime.now(timezone.utc)
        most_recent_days = None

        for node in community.graph_items:
            if not isinstance(node, dict):
                continue
            props = node.get("properties", {}) or {}
            raw_dt = props.get("last_reinforced") or props.get("timestamp") or props.get("created_at")
            if not isinstance(raw_dt, str):
                continue
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                days_ago = max(0.0, (now - dt).total_seconds() / 86400)
                if most_recent_days is None or days_ago < most_recent_days:
                    most_recent_days = days_ago
            except Exception:
                continue

        if most_recent_days is None:
            return 0.4
        return float(exp(-0.08 * most_recent_days))

    def _tokens(self, text: str) -> set[str]:
        """Normalize text into significant tokens."""
        raw = re.findall(r"[a-z0-9_]+", (text or "").lower())
        return {tok for tok in raw if len(tok) > 2 and tok not in self.STOP_WORDS}
