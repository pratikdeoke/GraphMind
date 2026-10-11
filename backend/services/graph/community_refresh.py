"""
Periodic community refresh service.

Builds stable community groupings from each user's graph and persists them into
Neo4j so global retrieval can leverage durable communities across sessions.
"""

import asyncio
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from neo4j import GraphDatabase

from config.settings import Settings
from services.database.user_service import UserService
from services.graph.community_selector import CommunityCandidate
from services.graph.community_persistence import CommunityPersistence


@dataclass
class RefreshStats:
    users_scanned: int = 0
    communities_upserted: int = 0
    stale_deleted: int = 0


class CommunityRefreshService:
    """Background worker to periodically recompute and persist user communities."""

    def __init__(self):
        self.enabled = Settings.COMMUNITY_REFRESH_ENABLED
        self.interval_seconds = max(300, Settings.COMMUNITY_REFRESH_INTERVAL_SECONDS)
        self.max_users_per_cycle = max(1, Settings.COMMUNITY_REFRESH_MAX_USERS_PER_CYCLE)
        self.max_nodes_per_user = max(50, Settings.COMMUNITY_REFRESH_MAX_NODES_PER_USER)
        self.max_edges_per_user = max(100, Settings.COMMUNITY_REFRESH_MAX_EDGES_PER_USER)
        self.user_prop_primary = "user_id"
        self.user_prop_fallback = "userId"
        self.id_prop_primary = "id"
        self.id_prop_fallback = "node_id"
        self.community_label = "Community"

        self.driver = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self.persistence = CommunityPersistence()

    async def start(self):
        if not self.enabled:
            print("[CommunityRefresh] Worker disabled")
            return

        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"[CommunityRefresh] Could not start worker: {e}")
            self.driver = None
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        print(
            "[CommunityRefresh] Worker started "
            f"(interval={self.interval_seconds}s, max_users={self.max_users_per_cycle})"
        )

    async def stop(self):
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[CommunityRefresh] Error while stopping worker: {e}")

        if self.driver:
            self.driver.close()
            self.driver = None

        self.persistence.close()
        print("[CommunityRefresh] Worker stopped")

    async def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                stats = await asyncio.to_thread(self.refresh_all_once)
                if stats.users_scanned > 0:
                    print(
                        f"[CommunityRefresh] users={stats.users_scanned}, "
                        f"communities_upserted={stats.communities_upserted}, "
                        f"stale_deleted={stats.stale_deleted}"
                    )
            except Exception as e:
                print(f"[CommunityRefresh] Refresh cycle failed: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    def refresh_all_once(self) -> RefreshStats:
        stats = RefreshStats()
        users = UserService.get_all_users(limit=self.max_users_per_cycle, offset=0)
        for user in users:
            user_id = user.get("neo4j_user_id") or user.get("id")
            if not user_id:
                continue
            upserted, deleted = self.refresh_user_once(str(user_id))
            stats.users_scanned += 1
            stats.communities_upserted += upserted
            stats.stale_deleted += deleted
        return stats

    def refresh_user_once(self, user_id: str) -> Tuple[int, int]:
        if not self.driver:
            return 0, 0

        nodes, edges = self._fetch_user_subgraph(user_id)
        if not nodes:
            deleted = self.persistence.prune_user_communities(user_id, keep_ids=[])
            return 0, deleted

        components = self._connected_components(nodes, edges)
        if not components:
            deleted = self.persistence.prune_user_communities(user_id, keep_ids=[])
            return 0, deleted

        communities = self._components_to_candidates(user_id, nodes, components)
        summaries = {community.id: self._summary_for_candidate(community) for community in communities}

        upserted = self.persistence.upsert_communities(
            user_id=user_id,
            communities=communities,
            summaries_by_id=summaries,
        )
        keep_ids = [community.id for community in communities]
        deleted = self.persistence.prune_user_communities(user_id, keep_ids=keep_ids)
        return upserted, deleted

    def _fetch_user_subgraph(self, user_id: str) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str]]]:
        node_map: Dict[str, Dict[str, Any]] = {}
        edges: List[Tuple[str, str]] = []

        try:
            with self.driver.session() as session:
                node_result = session.run(
                    """
                                        MATCH (n)
                                        WHERE coalesce(n[$user_prop_primary], n[$user_prop_fallback]) = $user_id
                                            AND coalesce(n[$id_prop_primary], n[$id_prop_fallback]) IS NOT NULL
                                            AND NOT $community_label IN labels(n)
                                        RETURN coalesce(n[$id_prop_primary], n[$id_prop_fallback]) AS id,
                           labels(n)[0] AS label,
                           properties(n) AS properties
                    LIMIT $limit
                    """,
                    user_id=user_id,
                                        user_prop_primary=self.user_prop_primary,
                                        user_prop_fallback=self.user_prop_fallback,
                                        id_prop_primary=self.id_prop_primary,
                                        id_prop_fallback=self.id_prop_fallback,
                                        community_label=self.community_label,
                    limit=self.max_nodes_per_user,
                )

                for row in node_result:
                    node_id = row.get("id")
                    if not node_id:
                        continue
                    node_map[str(node_id)] = {
                        "type": row.get("label") or "Entity",
                        "properties": row.get("properties") or {},
                    }

                if not node_map:
                    return {}, []

                edge_result = session.run(
                    """
                                        MATCH (a)-[r]-(b)
                                        WHERE coalesce(a[$user_prop_primary], a[$user_prop_fallback]) = $user_id
                                            AND coalesce(b[$user_prop_primary], b[$user_prop_fallback]) = $user_id
                                            AND coalesce(a[$id_prop_primary], a[$id_prop_fallback]) IS NOT NULL
                                            AND coalesce(b[$id_prop_primary], b[$id_prop_fallback]) IS NOT NULL
                                            AND NOT $community_label IN labels(a)
                                            AND NOT $community_label IN labels(b)
                                        RETURN DISTINCT
                                            coalesce(a[$id_prop_primary], a[$id_prop_fallback]) AS source,
                                            coalesce(b[$id_prop_primary], b[$id_prop_fallback]) AS target
                    LIMIT $limit
                    """,
                    user_id=user_id,
                                        user_prop_primary=self.user_prop_primary,
                                        user_prop_fallback=self.user_prop_fallback,
                                        id_prop_primary=self.id_prop_primary,
                                        id_prop_fallback=self.id_prop_fallback,
                                        community_label=self.community_label,
                    limit=self.max_edges_per_user,
                )

                for row in edge_result:
                    source = row.get("source")
                    target = row.get("target")
                    if not source or not target:
                        continue
                    source_id = str(source)
                    target_id = str(target)
                    if source_id in node_map and target_id in node_map:
                        edges.append((source_id, target_id))
        except Exception as e:
            print(f"[CommunityRefresh] Subgraph fetch error for {user_id}: {e}")

        return node_map, edges

    def _connected_components(
        self,
        nodes: Dict[str, Dict[str, Any]],
        edges: List[Tuple[str, str]],
    ) -> List[List[str]]:
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        for source, target in edges:
            adjacency[source].add(target)
            adjacency[target].add(source)

        visited: Set[str] = set()
        components: List[List[str]] = []

        for node_id in nodes.keys():
            if node_id in visited:
                continue
            queue = deque([node_id])
            visited.add(node_id)
            component: List[str] = []

            while queue:
                current = queue.popleft()
                component.append(current)
                for neighbor in adjacency.get(current, set()):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    queue.append(neighbor)

            components.append(component)

        components.sort(key=len, reverse=True)
        return components[:20]

    def _components_to_candidates(
        self,
        user_id: str,
        nodes: Dict[str, Dict[str, Any]],
        components: List[List[str]],
    ) -> List[CommunityCandidate]:
        candidates: List[CommunityCandidate] = []

        for idx, component in enumerate(components, start=1):
            graph_items = [nodes[node_id] for node_id in component if node_id in nodes]
            title = self._community_title(graph_items, idx)
            score = min(1.0, 0.35 + 0.05 * len(component))

            candidates.append(
                CommunityCandidate(
                    id=f"{user_id}_community_{idx}",
                    title=title,
                    graph_items=graph_items,
                    vector_items=[],
                    score=score,
                    score_breakdown={
                        "semantic": 0.5,
                        "centrality": score,
                        "recency": 0.5,
                    },
                )
            )

        return candidates

    def _community_title(self, graph_items: List[Dict[str, Any]], idx: int) -> str:
        type_counter = Counter()
        anchors: List[str] = []

        for node in graph_items:
            node_type = node.get("type", "Entity")
            type_counter[node_type] += 1
            props = node.get("properties", {}) or {}
            name = props.get("name") or props.get("normalized_name")
            if isinstance(name, str) and name.strip():
                anchors.append(name.strip())

        dominant_type = type_counter.most_common(1)[0][0] if type_counter else "Memory"
        anchor = anchors[0] if anchors else f"Group {idx}"
        return f"{dominant_type} Community - {anchor}"

    def _summary_for_candidate(self, candidate: CommunityCandidate) -> str:
        snippets: List[str] = []
        for node in candidate.graph_items[:6]:
            props = node.get("properties", {}) or {}
            node_type = node.get("type", "Entity")
            name = props.get("name") or props.get("text") or props.get("transaction_type") or "memory"
            snippets.append(f"{node_type}: {name}")

        if not snippets:
            return "No summary available for this community."

        return "; ".join(snippets)
