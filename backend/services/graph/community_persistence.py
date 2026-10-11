"""
Neo4j-backed community persistence for global retrieval.

Stores stable community ids/summaries and links memory nodes to communities so
global selection can reuse durable groups across sessions.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any
import re
from neo4j import GraphDatabase

from config.settings import Settings


class CommunityPersistence:
    """Persist and retrieve stable communities in Neo4j."""

    def __init__(self):
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not initialize community persistence: {e}")
            self.driver = None

    def upsert_communities(
        self,
        user_id: str,
        communities: List[Any],
        summaries_by_id: Dict[str, str],
    ) -> int:
        """Upsert communities and link member graph nodes to each community."""
        if not self.driver or not communities:
            return 0

        updated = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            with self.driver.session() as session:
                for community in communities:
                    community_id = community.id
                    summary = summaries_by_id.get(community_id, "")
                    score_breakdown = getattr(community, "score_breakdown", {}) or {}

                    session.run(
                        """
                        MERGE (c:Community {id: $community_id, user_id: $user_id})
                        ON CREATE SET c.created_at = datetime($now_iso)
                        SET c.title = $title,
                            c.summary = $summary,
                            c.score = $score,
                            c.semantic_score = $semantic_score,
                            c.centrality_score = $centrality_score,
                            c.recency_score = $recency_score,
                            c.updated_at = datetime($now_iso),
                            c.last_used_at = datetime($now_iso)
                        """,
                        community_id=community_id,
                        user_id=user_id,
                        title=community.title,
                        summary=summary,
                        score=float(getattr(community, "score", 0.0) or 0.0),
                        semantic_score=float(score_breakdown.get("semantic", 0.0) or 0.0),
                        centrality_score=float(score_breakdown.get("centrality", 0.0) or 0.0),
                        recency_score=float(score_breakdown.get("recency", 0.0) or 0.0),
                        now_iso=now_iso,
                    )

                    node_ids = []
                    for node in getattr(community, "graph_items", []) or []:
                        if not isinstance(node, dict):
                            continue
                        node_id = node.get("properties", {}).get("id")
                        if node_id:
                            node_ids.append(node_id)

                    if node_ids:
                        session.run(
                            """
                            UNWIND $node_ids AS node_id
                            MATCH (n {id: node_id, user_id: $user_id})
                            MATCH (c:Community {id: $community_id, user_id: $user_id})
                            MERGE (n)-[:IN_COMMUNITY]->(c)
                            """,
                            node_ids=node_ids,
                            community_id=community_id,
                            user_id=user_id,
                        )
                    updated += 1
        except Exception as e:
            print(f"Community upsert error: {e}")

        return updated

    def fetch_relevant_communities(self, user_id: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Fetch persisted communities ranked by lexical match and stored score."""
        if not self.driver:
            return []

        tokens = self._tokens(query)
        if not tokens:
            tokens = ["memory"]

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Community {user_id: $user_id})
                    WITH c,
                         reduce(
                           lex = 0.0,
                           token IN $tokens |
                           lex + CASE
                             WHEN toLower(c.title) CONTAINS token THEN 1.0
                             WHEN toLower(coalesce(c.summary, '')) CONTAINS token THEN 0.8
                             ELSE 0.0
                           END
                         ) AS lexical_score,
                         coalesce(c.score, 0.0) AS persisted_score,
                         coalesce(c.last_used_at, c.updated_at, c.created_at) AS freshness
                    RETURN
                      c.id AS id,
                      c.title AS title,
                      c.summary AS summary,
                      persisted_score,
                      lexical_score,
                      freshness
                    ORDER BY lexical_score DESC, persisted_score DESC, freshness DESC
                    LIMIT $top_k
                    """,
                    user_id=user_id,
                    tokens=tokens,
                    top_k=top_k,
                )

                communities = []
                for row in result:
                    communities.append(
                        {
                            "id": row.get("id"),
                            "title": row.get("title") or "Community",
                            "summary": row.get("summary") or "",
                            "persisted_score": float(row.get("persisted_score") or 0.0),
                            "lexical_score": float(row.get("lexical_score") or 0.0),
                        }
                    )
                return communities
        except Exception as e:
            print(f"Community fetch error: {e}")
            return []

    def prune_user_communities(self, user_id: str, keep_ids: List[str]) -> int:
        """Remove stale communities and old memberships not in keep_ids."""
        if not self.driver:
            return 0

        keep_ids = [value for value in keep_ids if value]

        try:
            with self.driver.session() as session:
                # Remove stale IN_COMMUNITY links first.
                session.run(
                    """
                    MATCH (n {user_id: $user_id})-[r:IN_COMMUNITY]->(c:Community {user_id: $user_id})
                    WHERE size($keep_ids) = 0 OR NOT c.id IN $keep_ids
                    DELETE r
                    """,
                    user_id=user_id,
                    keep_ids=keep_ids,
                )

                # Delete orphan or stale communities.
                result = session.run(
                    """
                    MATCH (c:Community {user_id: $user_id})
                    WHERE size($keep_ids) = 0 OR NOT c.id IN $keep_ids
                    OPTIONAL MATCH (c)<-[inRel:IN_COMMUNITY]-(:Entity {user_id: $user_id})
                    WITH c, count(inRel) AS member_count
                    WHERE member_count = 0
                    DETACH DELETE c
                    RETURN count(*) AS deleted_count
                    """,
                    user_id=user_id,
                    keep_ids=keep_ids,
                )
                row = result.single()
                return int(row["deleted_count"]) if row else 0
        except Exception as e:
            print(f"Community prune error: {e}")
            return 0

    def close(self):
        if self.driver:
            self.driver.close()

    def _tokens(self, text: str) -> List[str]:
        raw = re.findall(r"[a-z0-9_]+", (text or "").lower())
        return [token for token in raw if len(token) > 2]
