"""Neo4j schema bootstrap for retrieval performance.

Creates indexes that align with hot retrieval predicates and ordering fields.
"""

from __future__ import annotations

from typing import List

from neo4j import GraphDatabase

from config.settings import Settings


class SchemaBootstrapService:
    """Create retrieval-oriented Neo4j indexes if missing."""

    INDEX_STATEMENTS: List[str] = [
        "CREATE INDEX user_id_idx IF NOT EXISTS FOR (u:User) ON (u.id)",
        "CREATE INDEX message_user_id_idx IF NOT EXISTS FOR (m:Message) ON (m.user_id)",
        "CREATE INDEX message_user_time_idx IF NOT EXISTS FOR (m:Message) ON (m.user_id, m.created_at)",
        "CREATE INDEX fact_user_id_idx IF NOT EXISTS FOR (f:Fact) ON (f.user_id)",
        "CREATE INDEX fact_user_text_idx IF NOT EXISTS FOR (f:Fact) ON (f.user_id, f.text)",
        "CREATE INDEX fact_user_time_idx IF NOT EXISTS FOR (f:Fact) ON (f.user_id, f.created_at)",
        "CREATE INDEX transaction_user_id_idx IF NOT EXISTS FOR (t:Transaction) ON (t.user_id)",
        "CREATE INDEX transaction_user_time_idx IF NOT EXISTS FOR (t:Transaction) ON (t.user_id, t.created_at)",
        "CREATE INDEX transaction_user_type_idx IF NOT EXISTS FOR (t:Transaction) ON (t.user_id, t.transaction_type)",
        "CREATE INDEX asset_user_id_idx IF NOT EXISTS FOR (a:Asset) ON (a.user_id)",
        "CREATE INDEX asset_user_name_idx IF NOT EXISTS FOR (a:Asset) ON (a.user_id, a.name)",
        "CREATE INDEX asset_user_canonical_name_idx IF NOT EXISTS FOR (a:Asset) ON (a.user_id, a.canonical_name)",
        "CREATE INDEX goal_user_id_idx IF NOT EXISTS FOR (g:Goal) ON (g.user_id)",
        "CREATE INDEX goal_user_name_idx IF NOT EXISTS FOR (g:Goal) ON (g.user_id, g.name)",
        "CREATE INDEX community_user_id_idx IF NOT EXISTS FOR (c:Community) ON (c.user_id)",
        "CREATE INDEX retrieval_view_user_item_idx IF NOT EXISTS FOR (rv:RetrievalView) ON (rv.user_id, rv.item_id)",
        "CREATE INDEX retrieval_view_user_type_idx IF NOT EXISTS FOR (rv:RetrievalView) ON (rv.user_id, rv.item_type)",
        "CREATE INDEX retrieval_view_user_priority_idx IF NOT EXISTS FOR (rv:RetrievalView) ON (rv.user_id, rv.priority)",
        "CREATE INDEX ranker_feedback_user_item_idx IF NOT EXISTS FOR (rf:RankerFeedback) ON (rf.user_id, rf.item_key)",
    ]

    def __init__(self):
        self.driver = None
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"[SchemaBootstrap] Could not initialize Neo4j driver: {e}")
            self.driver = None

    def ensure_indexes(self) -> int:
        """Create indexes and return number of statements attempted."""
        if not self.driver:
            return 0

        executed = 0
        try:
            with self.driver.session() as session:
                for statement in self.INDEX_STATEMENTS:
                    try:
                        session.run(statement)
                        executed += 1
                    except Exception as e:
                        print(f"[SchemaBootstrap] Index statement failed: {e}")
        except Exception as e:
            print(f"[SchemaBootstrap] Index bootstrap failed: {e}")

        return executed

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None
