"""
Hybrid learned ranker for retrieval result calibration.

Combines graph/vector signals with recency, confidence, reinforcement, and
community hints. Supports per-mode weights and lightweight online feedback.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, log
from typing import Any, Dict, List, Optional

from services.graph.ranker_feedback_store import RankerFeedbackStore


@dataclass
class RankWeights:
    graph: float
    vector: float
    recency: float
    confidence: float
    reinforcement: float
    community: float


class HybridRanker:
    """Mode-aware hybrid ranker with lightweight user feedback calibration."""

    MODE_WEIGHTS: Dict[str, RankWeights] = {
        "basic": RankWeights(0.45, 0.30, 0.05, 0.10, 0.05, 0.05),
        "local": RankWeights(0.35, 0.20, 0.15, 0.15, 0.10, 0.05),
        "global": RankWeights(0.20, 0.10, 0.10, 0.10, 0.05, 0.45),
        "drift": RankWeights(0.25, 0.25, 0.15, 0.10, 0.10, 0.15),
    }

    def __init__(self, feedback_store: Optional[RankerFeedbackStore] = None):
        self._feedback_bias: Dict[str, Dict[str, float]] = {}
        self._loaded_users: set[str] = set()
        self.feedback_store = feedback_store or RankerFeedbackStore()

    def rank(
        self,
        user_id: str,
        strategy: str,
        fused_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Score and sort fused results by mode-aware hybrid ranking."""
        self._ensure_loaded(user_id)
        weights = self.MODE_WEIGHTS.get(strategy, self.MODE_WEIGHTS["local"])
        user_bias = self._feedback_bias.get(user_id, {})

        ranked: List[Dict[str, Any]] = []
        for item in fused_results:
            source = item.get("source", "graph")
            payload = item.get("payload", {}) or {}
            key = self._item_key(item)

            graph_signal = self._graph_signal(item)
            vector_signal = self._vector_signal(item)
            recency_signal = self._recency_signal(source, payload)
            confidence_signal = self._confidence_signal(item)
            reinforcement_signal = self._reinforcement_signal(source, payload)
            community_signal = self._community_signal(item)
            feedback_bias = user_bias.get(key, 0.0)

            score = (
                weights.graph * graph_signal
                + weights.vector * vector_signal
                + weights.recency * recency_signal
                + weights.confidence * confidence_signal
                + weights.reinforcement * reinforcement_signal
                + weights.community * community_signal
                + feedback_bias
            )
            score = max(0.0, min(1.0, score))

            enriched = dict(item)
            enriched["rank_key"] = key
            enriched["rank_score"] = round(score, 6)
            enriched["rank_breakdown"] = {
                "graph_signal": round(graph_signal, 4),
                "vector_signal": round(vector_signal, 4),
                "recency_signal": round(recency_signal, 4),
                "confidence_signal": round(confidence_signal, 4),
                "reinforcement_signal": round(reinforcement_signal, 4),
                "community_signal": round(community_signal, 4),
                "feedback_bias": round(feedback_bias, 4),
            }
            ranked.append(enriched)

        ranked.sort(key=lambda row: row.get("rank_score", 0.0), reverse=True)
        return ranked

    def update_feedback(self, user_id: str, cited_node_ids: List[str]):
        """Apply a small positive reinforcement bias for cited graph node ids."""
        if not cited_node_ids:
            return
        self._ensure_loaded(user_id)
        user_bias = self._feedback_bias.setdefault(user_id, {})
        changed: Dict[str, float] = {}
        for node_id in cited_node_ids:
            if not node_id:
                continue
            new_value = min(0.15, user_bias.get(node_id, 0.0) + 0.01)
            user_bias[node_id] = new_value
            changed[node_id] = new_value

        if changed and self.feedback_store:
            self.feedback_store.persist_user_bias(user_id, changed)

    def close(self):
        """Close persistent feedback store resources."""
        if self.feedback_store:
            self.feedback_store.close()

    def _ensure_loaded(self, user_id: str):
        """Load persisted user bias on first use for this process."""
        if not user_id or user_id in self._loaded_users:
            return
        if self.feedback_store:
            self._feedback_bias[user_id] = self.feedback_store.load_user_bias(user_id)
        else:
            self._feedback_bias[user_id] = {}
        self._loaded_users.add(user_id)

    def _item_key(self, item: Dict[str, Any]) -> str:
        source = item.get("source", "graph")
        payload = item.get("payload", {}) or {}
        if source == "graph":
            return str(payload.get("properties", {}).get("id") or payload.get("neo4j_id") or "graph_unknown")
        return str(payload.get("id") or payload.get("vector_id") or payload.get("text", "")[:64])

    def _graph_signal(self, item: Dict[str, Any]) -> float:
        payload = item.get("payload", {}) or {}
        fusion = float(item.get("fusion_score", 0.0) or 0.0)
        direct = float(payload.get("retrieval_score", fusion) or fusion)
        return max(0.0, min(1.0, 0.5 * fusion + 0.5 * direct))

    def _vector_signal(self, item: Dict[str, Any]) -> float:
        payload = item.get("payload", {}) or {}
        if item.get("source") == "vector":
            score = payload.get("similarity", payload.get("retrieval_score", 0.0))
            return max(0.0, min(1.0, float(score or 0.0)))
        return max(0.0, min(1.0, float(payload.get("vector_score", 0.0) or 0.0)))

    def _recency_signal(self, source: str, payload: Dict[str, Any]) -> float:
        now = datetime.now(timezone.utc)
        raw_dt = None
        if source == "graph":
            props = payload.get("properties", {}) or {}
            raw_dt = props.get("last_reinforced") or props.get("timestamp") or props.get("created_at")
        else:
            metadata = payload.get("metadata", {}) or {}
            raw_dt = metadata.get("timestamp") or payload.get("timestamp")

        if not isinstance(raw_dt, str):
            return 0.45

        try:
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            days_ago = max(0.0, (now - dt).total_seconds() / 86400)
            return float(exp(-0.08 * days_ago))
        except Exception:
            return 0.45

    def _confidence_signal(self, item: Dict[str, Any]) -> float:
        payload = item.get("payload", {}) or {}
        source = item.get("source")
        if source == "graph":
            props = payload.get("properties", {}) or {}
            conf = payload.get("confidence", props.get("confidence", item.get("confidence", 0.5)))
        else:
            conf = payload.get("confidence", payload.get("similarity", item.get("confidence", 0.5)))
        return max(0.0, min(1.0, float(conf or 0.0)))

    def _reinforcement_signal(self, source: str, payload: Dict[str, Any]) -> float:
        if source != "graph":
            return 0.0
        props = payload.get("properties", {}) or {}
        count = int(props.get("reinforcement_count", 0) or 0)
        if count <= 0:
            return 0.0
        return min(1.0, log(1 + count) / log(10))

    def _community_signal(self, item: Dict[str, Any]) -> float:
        payload = item.get("payload", {}) or {}
        if "community_score" in payload:
            return max(0.0, min(1.0, float(payload.get("community_score") or 0.0)))

        source = item.get("source")
        if source == "graph":
            node_type = str(payload.get("type", ""))
            if node_type == "Goal":
                return 0.65
            if node_type in {"Asset", "Transaction", "Fact"}:
                return 0.55
            return 0.45

        source_type = str(payload.get("source_type", ""))
        if "community" in source_type:
            return 0.7
        return 0.4
