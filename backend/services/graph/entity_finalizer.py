"""
Entity finalization service for Neo4j-backed ingestion.

Adds post-ingestion enrichment used by advanced retrieval ranking:
- Canonical name normalization
- Node degree and combined_degree features
- Relationship combined_degree enrichment
"""

from __future__ import annotations

from typing import Dict

from neo4j import GraphDatabase

from config.settings import Settings


class EntityFinalizer:
    """Post-ingestion graph finalization for a specific user graph."""

    def __init__(self):
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not initialize EntityFinalizer: {e}")
            self.driver = None

    def finalize_user_graph(self, user_id: str) -> Dict[str, int]:
        """Compute retrieval-friendly graph features for one user graph."""
        if not self.driver or not user_id:
            return {
                "finalizer_nodes_updated": 0,
                "finalizer_relationships_updated": 0,
            }

        nodes_updated = 0
        rels_updated = 0
        views_updated = 0

        try:
            with self.driver.session() as session:
                # Normalize names to canonical_name for light dedup and matching.
                name_res = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE n.name IS NOT NULL
                    SET n.canonical_name = toLower(trim(n.name)),
                        n.updated_at = datetime()
                    RETURN count(n) AS updated
                    """,
                    user_id=user_id,
                ).single()
                nodes_updated += int(name_res["updated"]) if name_res else 0

                # Node degree features.
                deg_res = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE NOT n:User
                    OPTIONAL MATCH (n)-[r]-()
                    WITH n, count(r) AS degree
                    SET n.degree = degree,
                        n.combined_degree = degree,
                        n.updated_at = datetime()
                    RETURN count(n) AS updated
                    """,
                    user_id=user_id,
                ).single()
                nodes_updated += int(deg_res["updated"]) if deg_res else 0

                # Relationship combined-degree feature.
                rel_res = session.run(
                    """
                    MATCH (a {user_id: $user_id})-[r]->(b {user_id: $user_id})
                    WITH r, coalesce(a.degree, 0) + coalesce(b.degree, 0) AS combined_degree
                    SET r.combined_degree = combined_degree,
                        r.updated_at = datetime()
                    RETURN count(r) AS updated
                    """,
                    user_id=user_id,
                ).single()
                rels_updated += int(rel_res["updated"]) if rel_res else 0

                # Materialized retrieval views: precomputed top candidates per user.
                session.run(
                    """
                    MATCH (rv)
                    WHERE 'RetrievalView' IN labels(rv)
                      AND rv['user_id'] = $user_id
                    DETACH DELETE rv
                    """,
                    user_id=user_id,
                )

                views_res = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE NOT n:User
                      AND coalesce(n.id, '') <> ''
                    WITH n,
                         labels(n)[0] AS node_type,
                         coalesce(n.combined_degree, n.degree, 0) AS degree_score,
                         coalesce(n.confidence, 0.5) AS confidence_score,
                         coalesce(n.reinforcement_count, 0) AS reinforcement_score,
                         coalesce(n.updated_at, n.last_reinforced, n.created_at, n.timestamp) AS freshness
                    WITH n, node_type,
                         (0.55 * degree_score) +
                         (0.30 * confidence_score) +
                         (0.15 * reinforcement_score) AS retrieval_priority,
                         freshness
                    ORDER BY retrieval_priority DESC, freshness DESC
                    LIMIT 200
                    MERGE (rv:RetrievalView {user_id: $user_id, item_id: n.id})
                    SET rv.item_type = node_type,
                        rv.priority = retrieval_priority,
                        rv.updated_at = datetime()
                    MERGE (rv)-[:VIEW_OF]->(n)
                    RETURN count(rv) AS updated
                    """,
                    user_id=user_id,
                ).single()
                views_updated += int(views_res["updated"]) if views_res else 0

        except Exception as e:
            print(f"Entity finalization error for {user_id}: {e}")

        return {
            "finalizer_nodes_updated": nodes_updated,
            "finalizer_relationships_updated": rels_updated,
            "finalizer_views_updated": views_updated,
        }

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None
