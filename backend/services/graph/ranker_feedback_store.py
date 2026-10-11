"""
Persistent store for hybrid ranker feedback bias.

Uses Neo4j to persist per-user, per-item bias so rank calibration survives
service restarts.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from neo4j import GraphDatabase

from config.settings import Settings


class RankerFeedbackStore:
    """Read/write storage for ranker feedback bias values."""

    def __init__(self):
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not initialize ranker feedback store: {e}")
            self.driver = None

    def load_user_bias(self, user_id: str) -> Dict[str, float]:
        if not self.driver or not user_id:
            return {}

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (f)
                    WHERE 'RankerFeedback' IN labels(f)
                      AND f.user_id = $user_id
                    RETURN properties(f) AS props
                    LIMIT 5000
                    """,
                    user_id=user_id,
                )
                bias: Dict[str, float] = {}
                for row in result:
                    props = row.get("props") or {}
                    item_key = props.get("item_key")
                    if not item_key:
                        continue
                    bias[str(item_key)] = float(props.get("bias") or 0.0)
                return bias
        except Exception as e:
            print(f"Ranker feedback load error: {e}")
            return {}

    def persist_user_bias(self, user_id: str, updates: Dict[str, float]) -> int:
        if not self.driver or not user_id or not updates:
            return 0

        rows = [
            {"item_key": key, "bias": float(value)}
            for key, value in updates.items()
            if key
        ]
        if not rows:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (f:RankerFeedback {user_id: $user_id, item_key: row.item_key})
                    ON CREATE SET f.created_at = datetime($now_iso)
                    SET f.bias = row.bias,
                        f.updated_at = datetime($now_iso)
                    RETURN count(f) AS updated_count
                    """,
                    user_id=user_id,
                    rows=rows,
                    now_iso=now_iso,
                )
                rec = result.single()
                return int(rec["updated_count"]) if rec else 0
        except Exception as e:
            print(f"Ranker feedback persist error: {e}")
            return 0

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None
