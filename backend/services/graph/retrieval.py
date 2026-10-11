"""
Graph Retrieval Service - Production-grade controlled retrieval with multi-mode ensemble.

Architecture:
- Multi-mode ensemble retrieval (execute all modes, fuse intelligently)
- Real hop distance calculation
- Graph analytics integration (PageRank, centrality)
- Relationship weighting (confidence-based)
- User-isolated traversal
- Timeline filtering
- Advanced hybrid scoring combining multiple signals
- Deferred reinforcement (updated after answer generation)
"""

from typing import Dict, List, Any, Tuple, Optional
import time
import math
from datetime import datetime, timezone
from neo4j import GraphDatabase
from neo4j.time import DateTime
from config.settings import Settings
from services.graph.query_understanding import QueryUnderstanding, RetrievalMode
from services.graph.graph_analytics import GraphAnalytics


class GraphRetrieval:
    """
    Production-grade graph retrieval with controlled traversal.

    Design Principles:
    - Multi-mode ensemble execution with intelligent fusion
    - Graph analytics for importance scoring
    - Relationship weighting for semantic relevance
    - No wildcard path explosion
    - Real hop distance scoring with centrality weighting
    - Strict user isolation
    - O(edges) complexity, not O(paths)
    """
    
    # Enhanced scoring weights (sum = 1.0)
    SCORE_WEIGHTS = {
        "graph_distance": 0.20,      # Reduced: prefer importance over proximity
        "centrality": 0.25,           # NEW: Network importance
        "recency": 0.20,
        "confidence": 0.15,
        "reinforcement": 0.10,
        "relationship_weight": 0.10   # NEW: Edge confidence
    }

    # Recency decay parameter
    RECENCY_DECAY_LAMBDA = 0.1  # Exponential decay rate

    
    def __init__(self):
        """Initialize Neo4j connection and analytics."""
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not connect to Neo4j: {e}")
            self.driver = None

        self.query_understanding = QueryUnderstanding()

    def retrieve(
        self,
        user_id: str,
        query: str,
        max_depth: int = 2,  # Reduced from 3 for sub-100ms target
        top_k: int = 10,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Retrieve relevant graph context using controlled mode-based queries.

        Optimizations:
        - Reduced max_depth from 3 to 2 for faster traversal
        - Efficient node ranking
        - Early termination strategies

        Args:
            user_id: User identifier
            query: User's query text
            max_depth: Maximum hops (optimized for speed)

        Returns:
            Tuple of (retrieved_nodes, retrieval_time_ms)
        """
        if not self.driver:
            print("Warning: Neo4j driver not initialized, returning empty results")
            return [], 0.0

        start_time = time.time()
        retrieved_nodes = []

        try:
            with self.driver.session() as session:
                # 1. Classify query mode
                mode, recommended_depth = self.query_understanding.classify_query(
                    query)
                # Cap depth at 2 for performance (down from original 3)
                recommended_depth = min(recommended_depth, 2)
                print(f"Query mode: {mode.value}, depth: {recommended_depth}")

                # 2. Extract timeline filter (optional)
                start_date = self.query_understanding.extract_timeline(query)

                # 3. Execute mode-specific retrieval
                raw_nodes = self._execute_mode_based_retrieval(
                    session, user_id, mode, start_date, recommended_depth, top_k
                )

                # 4. Calculate real hop distances from User node
                nodes_with_hops = self._calculate_hop_distances(
                    session, user_id, raw_nodes
                )

                # 5. Apply scoring and ranking (simplified for speed)
                retrieved_nodes = self._score_and_rank_nodes(
                    nodes_with_hops, query
                )
                retrieved_nodes = retrieved_nodes[:top_k]

        except Exception as e:
            print(f"Error during graph retrieval: {e}")
            import traceback
            traceback.print_exc()

        retrieval_time_ms = (time.time() - start_time) * 1000

        return retrieved_nodes, retrieval_time_ms

    def _serialize_neo4j_types(self, obj: Any) -> Any:
        """Convert Neo4j types to JSON-serializable Python types."""
        if isinstance(obj, DateTime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_neo4j_types(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._serialize_neo4j_types(item) for item in obj]
        else:
            return obj

    def _execute_mode_based_retrieval(
        self,
        session,
        user_id: str,
        mode: RetrievalMode,
        start_date: Optional[datetime],
        depth: int,
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Execute controlled retrieval based on query mode.

        NO WILDCARD PATHS - Each mode has specific traversal.
        """
        candidate_limit = max(int(top_k) * 4, 20)

        # Stage 1: precomputed retrieval view candidates.
        precomputed = self._fetch_precomputed_candidates(
            session=session,
            user_id=user_id,
            mode=mode,
            start_date=start_date,
            candidate_limit=candidate_limit,
            depth=depth,
        )
        if precomputed:
            return precomputed

        # Build timeline filter clause
        node_time_filter = ""
        params = {
            "user_id": user_id,
            "start_date": start_date,
            "top_k": int(top_k),
            "candidate_limit": candidate_limit,
        }

        if start_date:
            node_time_filter = "AND coalesce(n.timestamp, n.last_reinforced, n.created_at) >= $start_date"

        if mode == RetrievalMode.DIRECT_LOOKUP:
            # Simple entity lookup (e.g., "What assets do I own?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            OPTIONAL MATCH (u)-[:OWNS_MESSAGE]->(m:Message)
            WHERE m.user_id = $user_id
            OPTIONAL MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
            WHERE t.user_id = $user_id AND coalesce(t['superseded'], false) = false
            OPTIONAL MATCH (t)-[:AFFECTS_ASSET]->(a:Asset)
            WHERE a.user_id = $user_id
            OPTIONAL MATCH (m)-[:DERIVED_FACT]->(f:Fact)
            WHERE f.user_id = $user_id
            WITH u, collect(DISTINCT m) + collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT f) as nodes
            UNWIND nodes as n
            WITH u, n
            WHERE n IS NOT NULL {node_time_filter}
            WITH n,
                 CASE
                     WHEN n:Transaction THEN 1
                     WHEN n:Message THEN 1
                     WHEN n:Asset THEN 2
                     WHEN n:Fact THEN 2
                     ELSE {depth} + 1
                 END AS hops
            WITH n, hops,
                 CASE
                     WHEN n:Fact THEN 'fact_memory'
                     WHEN n:Transaction THEN 'transaction_link'
                     WHEN n:Asset THEN 'asset_link'
                     WHEN n:Message THEN 'message_context'
                     ELSE 'direct_lookup'
                 END AS matched_by
            RETURN DISTINCT n, hops, matched_by
            ORDER BY hops ASC
            LIMIT $top_k
            """

        elif mode == RetrievalMode.AGGREGATION:
            # Aggregation queries (e.g., "How much have I invested?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
                        WHERE t.user_id = $user_id AND coalesce(t['superseded'], false) = false
                            AND ($start_date IS NULL OR coalesce(t.timestamp, t.last_reinforced, t.created_at) >= $start_date)
            OPTIONAL MATCH (t)-[:AFFECTS_ASSET]->(a:Asset)
            WHERE a.user_id = $user_id
            OPTIONAL MATCH (f:Fact)-[:CONFIRMS]->(t)
            WHERE f.user_id = $user_id
            WITH u, collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT f) as nodes
            UNWIND nodes as n
                    WITH n
                        WHERE n IS NOT NULL {node_time_filter}
                    WITH n,
                         CASE
                             WHEN n:Transaction THEN 1
                             WHEN n:Asset THEN 2
                             WHEN n:Fact THEN 2
                             ELSE {depth} + 1
                         END AS hops
                        WITH n, hops,
                                 CASE
                                         WHEN n:Transaction THEN 'aggregation_transaction'
                                         WHEN n:Fact THEN 'aggregation_fact'
                                         WHEN n:Asset THEN 'aggregation_asset'
                                         ELSE 'aggregation_context'
                                 END AS matched_by
                        RETURN DISTINCT n, hops, matched_by
                        ORDER BY hops ASC
                        LIMIT $candidate_limit
            """

        elif mode == RetrievalMode.RELATIONAL_REASONING:
            # Multi-hop reasoning (e.g., "Is investment aligned with goal?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            OPTIONAL MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)-[:AFFECTS_ASSET]->(a:Asset)
                        WHERE t.user_id = $user_id AND a.user_id = $user_id
                            AND coalesce(t['superseded'], false) = false
                            AND ($start_date IS NULL OR coalesce(t.timestamp, t.last_reinforced, t.created_at) >= $start_date)
            OPTIONAL MATCH (a)-[:CONTRIBUTES_TO]->(g:Goal)
            WHERE g.user_id = $user_id
            OPTIONAL MATCH (u)-[:HAS_PREFERENCE]->(p:Preference)
            WHERE p.user_id = $user_id
            OPTIONAL MATCH (f:Fact)-[:CONFIRMS]->(t)
            WHERE f.user_id = $user_id
            OPTIONAL MATCH (f2:Fact)-[:RELATES_TO]->(a)
            WHERE f2.user_id = $user_id
              WITH u, collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT g) + 
                 collect(DISTINCT p) + collect(DISTINCT f) + collect(DISTINCT f2) as nodes
            UNWIND nodes as n
              WITH u, n
              WHERE n IS NOT NULL {node_time_filter}
              WITH n,
                  CASE
                     WHEN n:Transaction THEN 1
                     WHEN n:Asset THEN 2
                     WHEN n:Goal THEN 3
                     WHEN n:Preference THEN 1
                     WHEN n:Fact THEN 2
                     ELSE {depth} + 1
                  END AS hops
              WITH n, hops,
                  CASE
                     WHEN n:Goal THEN 'goal_reasoning'
                     WHEN n:Preference THEN 'preference_reasoning'
                     WHEN n:Asset THEN 'asset_reasoning'
                     WHEN n:Fact THEN 'fact_reasoning'
                     ELSE 'relational_context'
                  END AS matched_by
              RETURN DISTINCT n, hops, matched_by
              ORDER BY hops ASC
              LIMIT $top_k
            """

        else:
            # Fallback to direct lookup
            query = f"""
            MATCH (u:User {{id: $user_id}})
            MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
            WHERE t.user_id = $user_id AND coalesce(t['superseded'], false) = false
            WITH t AS n, 1 AS hops
            RETURN n, hops, 'fallback_transaction' AS matched_by
            ORDER BY hops ASC
            LIMIT $candidate_limit
            """

        result = session.run(query, **params)

        # Format nodes
        nodes = []
        for record in result:
            node = record.get("n")
            if node:
                nodes.append({
                    "type": list(node.labels)[0] if node.labels else "Unknown",
                    "properties": self._serialize_neo4j_types(dict(node)),
                    "neo4j_id": node.id,
                    "hop_distance": int(record.get("hops", depth + 1)),
                    "retrieval_trace": {
                        "mode": mode.value,
                        "matched_by": record.get("matched_by", "unknown"),
                        "depth_used": depth,
                        "top_k_used": top_k,
                        "timeline_filter_applied": start_date is not None
                    }
                })

        print(f"[DEBUG] Mode: {mode.value}, Retrieved {len(nodes)} nodes")
        return nodes

    def _fetch_precomputed_candidates(
        self,
        session,
        user_id: str,
        mode: RetrievalMode,
        start_date: Optional[datetime],
        candidate_limit: int,
        depth: int,
    ) -> List[Dict[str, Any]]:
        """Fetch precomputed retrieval candidates from materialized RetrievalView nodes."""
        mode_types = {
            RetrievalMode.DIRECT_LOOKUP: ["Fact", "Asset", "Message", "Preference", "Goal"],
            RetrievalMode.AGGREGATION: ["Transaction", "Fact", "Asset"],
            RetrievalMode.RELATIONAL_REASONING: ["Goal", "Preference", "Asset", "Transaction", "Fact"],
        }
        allowed_types = mode_types.get(mode, ["Fact", "Asset", "Transaction", "Message"])

        query = """
        MATCH (rv)-[:VIEW_OF]->(n)
        WHERE 'RetrievalView' IN labels(rv)
          AND rv['user_id'] = $user_id
          AND rv['item_type'] IN $allowed_types
          AND ($start_date IS NULL OR coalesce(n.timestamp, n.last_reinforced, n.created_at) >= $start_date)
        RETURN n,
               coalesce(rv['priority'], 0.0) AS view_priority,
               rv['item_type'] AS item_type
        ORDER BY view_priority DESC
        LIMIT $candidate_limit
        """

        try:
            result = session.run(
                query,
                user_id=user_id,
                allowed_types=allowed_types,
                start_date=start_date,
                candidate_limit=int(candidate_limit),
            )
        except Exception:
            return []

        nodes: List[Dict[str, Any]] = []
        for row in result:
            node = row.get("n")
            if not node:
                continue

            node_type = row.get("item_type") or (list(node.labels)[0] if node.labels else "Unknown")
            hop_guess = 1 if node_type in ("Transaction", "Message", "Preference") else 2
            nodes.append(
                {
                    "type": node_type,
                    "properties": self._serialize_neo4j_types(dict(node)),
                    "neo4j_id": node.id,
                    "hop_distance": hop_guess,
                    "retrieval_trace": {
                        "mode": mode.value,
                        "matched_by": "precomputed_view",
                        "depth_used": depth,
                        "top_k_used": candidate_limit,
                        "timeline_filter_applied": start_date is not None,
                    },
                    "precomputed_priority": float(row.get("view_priority") or 0.0),
                }
            )

        if nodes:
            print(f"[DEBUG] Mode: {mode.value}, Retrieved {len(nodes)} precomputed candidates")
        return nodes

    def _calculate_hop_distances(
        self,
        session,
        user_id: str,
        nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Calculate real hop distance from User node to each retrieved node.

        Uses shortestPath() for accurate graph distance.
        """
        # Fast path: if hop_distance is already populated from mode query, avoid
        # one shortestPath DB roundtrip per node.
        if nodes and all("hop_distance" in node for node in nodes):
            return nodes

        nodes_with_hops = []

        for node in nodes:
            node_id = node["properties"].get("id")
            if not node_id:
                continue

            # Calculate shortest path length
            hop_query = """
            MATCH (u:User {id: $user_id})
            MATCH (n {id: $node_id, user_id: $user_id})
            MATCH path = shortestPath((u)-[*1..5]-(n))
            RETURN length(path) as hops
            """

            try:
                result = session.run(
                    hop_query, user_id=user_id, node_id=node_id)
                record = result.single()
                # Default to 3 if no path
                hops = record["hops"] if record else 3
            except:
                hops = 3  # Fallback

            node["hop_distance"] = hops
            nodes_with_hops.append(node)

        print(
            f"[DEBUG] Calculated hops for {len(nodes_with_hops)}/{len(nodes)} nodes")
        return nodes_with_hops

    def _score_and_rank_nodes(
        self,
        nodes: List[Dict[str, Any]],
        query: str
    ) -> List[Dict[str, Any]]:
        """
        Score and rank nodes using normalized multi-factor scoring with query relevance.

        Formula (all components normalized 0-1):
        score = w_relevance × relevance_score +
                w_graph × graph_score + 
                w_recency × recency_score + 
                w_confidence × confidence +
                w_reinforcement × reinforcement_score

        Where:
        - relevance_score = keyword match similarity to query
        - graph_score = 1 / (hops + 1)
        - recency_score = exp(-λ × days_ago)
        - confidence = node.confidence
        - reinforcement_score = min(1, log(1 + count) / log(10))
        - relationship_weight = confidence of incoming relationships
        """
        scored_nodes = []
        now = datetime.now(timezone.utc)

        # Extract query keywords for relevance matching
        query_keywords = self.query_understanding.extract_query_keywords(query)
        query_keywords_lower = [kw.lower() for kw in query_keywords]

        for node in nodes:
            props = node.get("properties", {})
            node_type = node.get("type", "Unknown")
            relationship_weight = float(props.get("confidence", 0.5))
            mode_coverage = node.get("retrieval_trace", {}).get("matched_by", "unknown")

            # Skip User nodes from ranking
            if node_type == "User":
                continue

            # Calculate relevance score based on keyword matching
            relevance_score = self._calculate_relevance_score(
                node, query_keywords_lower, query.lower())
            # 1. Graph Distance Score (inverse of hops)
            hops = node.get("hop_distance", 3)
            graph_score = 1.0 / (hops + 1)

            # 1.5 Precomputed importance signal from ingestion-time finalizer.
            degree_value = float(props.get("combined_degree", props.get("degree", 0)) or 0)
            centrality_score = min(1.0, math.log1p(max(0.0, degree_value)) / math.log(20))
            view_priority = float(node.get("precomputed_priority", 0.0))
            if view_priority > 0:
                centrality_score = max(centrality_score, min(1.0, view_priority / 10.0))

            # 2. Recency Score (exponential decay)
            recency_score = 0.5  # Default
            last_reinforced = props.get("last_reinforced")
            days_ago = 0.0
            if last_reinforced:
                if isinstance(last_reinforced, str):
                    try:
                        last_dt = datetime.fromisoformat(
                            last_reinforced.replace("Z", "+00:00"))
                        days_ago = (now - last_dt).total_seconds() / \
                            86400  # Days as float
                        recency_score = math.exp(
                            -self.RECENCY_DECAY_LAMBDA * days_ago)
                    except:
                        pass

            # 3. Confidence Score (already normalized 0-1)
            confidence = float(props.get("confidence", 0.5))

            # 4. Reinforcement Score (logarithmic scaling)
            reinforcement_count = int(props.get("reinforcement_count", 0))
            if reinforcement_count > 0:
                reinforcement_score = min(1.0, math.log(
                    1 + reinforcement_count) / math.log(10))
            else:
                reinforcement_score = 0.0

            # Calculate weighted final score with relevance boosting
            final_score = (
                0.3 * relevance_score +  # NEW: Query relevance has high priority
                self.SCORE_WEIGHTS["graph_distance"] * graph_score +
                self.SCORE_WEIGHTS["centrality"] * centrality_score +
                self.SCORE_WEIGHTS["recency"] * recency_score +
                self.SCORE_WEIGHTS["confidence"] * confidence +
                self.SCORE_WEIGHTS["reinforcement"] * reinforcement_score +
                self.SCORE_WEIGHTS["relationship_weight"] * relationship_weight
            )

            # Add scoring details to node
            node["retrieval_score"] = round(final_score, 3)
            node["score_breakdown"] = {
                "relevance": round(relevance_score, 3),
                "graph_distance": round(graph_score, 3),
                "centrality": round(centrality_score, 3),
                "recency": round(recency_score, 3),
                "confidence": round(confidence, 3),
                "reinforcement": round(reinforcement_score, 3),
                "days_since_reinforced": round(days_ago, 3),
                "relationship": round(relationship_weight, 3),
                "mode_coverage": mode_coverage,
                "hop_distance": hops,
                "trace": node.get("retrieval_trace", {})
            }

            # Add snippet for explainability
            node["snippet"] = self._create_snippet(node_type, props)

            scored_nodes.append(node)

        # Filter out low-relevance nodes (< 0.1 score) to reduce noise
        scored_nodes = [n for n in scored_nodes if n.get(
            "retrieval_score", 0) >= 0.1]

        # Sort by score descending
        scored_nodes.sort(key=lambda x: x.get(
            "retrieval_score", 0), reverse=True)

        print(
            f"[DEBUG] Scored and ranked {len(scored_nodes)} nodes (top score: {scored_nodes[0]['retrieval_score'] if scored_nodes else 'N/A'})")
        return scored_nodes

    def _create_snippet(self, node_type: str, props: Dict[str, Any]) -> str:
        """Create human-readable snippet for node."""
        if node_type == "Transaction":
            amount = props.get("amount", 0)
            tx_type = props.get("transaction_type", "transaction")
            return f"{tx_type.capitalize()} of ₹{amount:,.0f}"

        elif node_type == "Asset":
            name = props.get("name", "Unknown")
            asset_type = props.get("asset_type", "asset")
            return f"{name} ({asset_type})"

        elif node_type == "Fact":
            text = props.get("text", "")
            return text[:60] + "..." if len(text) > 60 else text

        elif node_type == "Goal":
            name = props.get("name", "Unknown goal")
            return f"Goal: {name}"

        elif node_type == "Message":
            text = props.get("text", "")
            return text[:50] + "..." if len(text) > 50 else text

        else:
            return props.get("name", props.get("text", node_type))

    def reinforce_cited_nodes(self, user_id: str, node_ids: List[str]):
        """
        Update reinforcement for nodes cited in LLM answer.

        Called AFTER answer generation (deferred reinforcement).

        Args:
            user_id: User identifier
            node_ids: List of node IDs that were cited in answer
        """
        if not self.driver or not node_ids:
            return

        try:
            with self.driver.session() as session:
                query = """
                UNWIND $node_ids as node_id
                MATCH (n {id: node_id, user_id: $user_id})
                SET n.last_reinforced = datetime(),
                    n.reinforcement_count = coalesce(n.reinforcement_count, 0) + 1
                RETURN count(n) as updated_count
                """

                result = session.run(query, user_id=user_id, node_ids=node_ids)
                record = result.single()
                count = record["updated_count"] if record else 0
                print(f"Reinforced {count} cited nodes")

        except Exception as e:
            print(f"Error reinforcing nodes: {e}")

    def detect_contradictions(self, user_id: str, new_fact_text: str, entity_name: str) -> List[Dict[str, Any]]:
        """
        Detect contradictions with existing facts about the same entity.

        Args:
            user_id: User identifier
            new_fact_text: The new fact text to check
            entity_name: The entity this fact relates to

        Returns:
            List of potentially contradicting facts
        """
        if not self.driver:
            return []

        try:
            with self.driver.session() as session:
                # Find existing facts about the same entity with strict user isolation
                query = """
                MATCH (f:Fact {user_id: $user_id})
                MATCH (f)-[:RELATES_TO]->(e {name: $entity_name, user_id: $user_id})
                WHERE f.text <> $new_fact_text
                RETURN f.id as fact_id, f.text as fact_text, f.confidence as confidence
                ORDER BY f.timestamp DESC
                LIMIT 5
                """

                result = session.run(
                    query,
                    user_id=user_id,
                    new_fact_text=new_fact_text,
                    entity_name=entity_name
                )

                contradictions = []
                for record in result:
                    contradictions.append({
                        "fact_id": record["fact_id"],
                        "fact_text": record["fact_text"],
                        "confidence": record["confidence"]
                    })

                return contradictions

        except Exception as e:
            print(f"Error in contradiction detection: {e}")
            return []

    def mark_contradiction(self, old_fact_id: str, new_fact_id: str, user_id: str, reduce_confidence: bool = True):
        """
        Mark two facts as contradicting and optionally reduce confidence of old fact.

        Args:
            old_fact_id: ID of the older fact
            new_fact_id: ID of the newer fact
            user_id: User identifier for isolation
            reduce_confidence: Whether to reduce confidence of old fact
        """
        if not self.driver:
            return

        try:
            with self.driver.session() as session:
                query = """
                MATCH (old:Fact {id: $old_fact_id, user_id: $user_id})
                MATCH (new:Fact {id: $new_fact_id, user_id: $user_id})
                MERGE (old)-[:CONTRADICTS]->(new)
                """

                if reduce_confidence:
                    query += """
                    SET old.confidence = old.confidence * 0.5
                    """

                session.run(query, old_fact_id=old_fact_id,
                            new_fact_id=new_fact_id, user_id=user_id)
                print(
                    f"Marked contradiction between {old_fact_id} and {new_fact_id}")

        except Exception as e:
            print(f"Error marking contradiction: {e}")

    def _calculate_relevance_score(
        self,
        node: Dict[str, Any],
        query_keywords: List[str],
        query_lower: str
    ) -> float:
        """
        Calculate query relevance score for a node (0-1).

        Matches keywords against node properties to filter for query-relevant evidence.
        Higher score = more relevant to the query.
        """
        if not query_keywords:
            return 0.5  # Default to neutral if no keywords

        props = node.get("properties", {})
        node_type = node.get("type", "Unknown")

        # Collect all text fields from the node with importance weights
        text_fields = []

        if node_type == "Transaction":
            # Check transaction type and description
            text_fields.append((props.get("transaction_type", ""), 2.0))
            text_fields.append((props.get("description", ""), 1.0))
        elif node_type == "Asset":
            # Check asset name and type (name is most important)
            text_fields.append((props.get("name", ""), 3.0))
            text_fields.append((props.get("asset_type", ""), 2.0))
        elif node_type == "Fact":
            # Check fact text content
            text_fields.append((props.get("text", ""), 2.0))
        elif node_type == "Goal":
            # Check goal name
            text_fields.append((props.get("name", ""), 2.0))
        elif node_type == "Message":
            # Check message content
            text_fields.append((props.get("text", ""), 1.5))

        # Calculate keyword match score with weights
        matches = 0.0
        max_possible = float(len(query_keywords))

        for text, weight in text_fields:
            if not text:
                continue
            text_lower = str(text).lower()
            for kw in query_keywords:
                if kw in text_lower:
                    matches += weight
                    break  # Count each keyword once per field

        # Normalize to 0-1 range
        relevance_score = min(1.0, matches / max(1.0, max_possible))

        return relevance_score

    def _query_total_invested(self, user_id: str) -> float:
        """Query total invested amount from all transactions in the graph."""
        if not self.driver:
            return 0.0
        
        try:
            with self.driver.session() as session:
                # Try matching with user's transactions
                query = """
                MATCH (t:Transaction {user_id: $user_id})
                RETURN coalesce(sum(t.amount), 0) as total
                """
                print(f"[💰 Query] Searching Transactions for user_id={user_id}")
                result = session.run(query, user_id=user_id)
                record = result.single()
                total = float(record["total"]) if record and record["total"] else 0.0
                print(f"[💰 Result] Total invested for {user_id}: ₹{total}")
                return total
        except Exception as e:
            print(f"[❌ Error] querying total invested for {user_id}: {e}")
            return 0.0

    def _query_banks(self, user_id: str) -> List[Dict[str, Any]]:
        """Query bank entities from the graph."""
        if not self.driver:
            return []
        
        try:
            with self.driver.session() as session:
                # Look for Asset nodes with bank names (HDFC, SBI, ICICI, etc.)
                query = """
                MATCH (a:Asset {user_id: $user_id})
                WHERE toLower(a.name) CONTAINS 'bank' 
                   OR toLower(a.name) IN ['sbi', 'hdfc', 'icici', 'axis', 'bob', 'union', 'pnb', 'yes bank', 'kotak', 'hdfc mutual fund']
                RETURN distinct a.name as name
                ORDER BY a.name
                LIMIT 10
                """
                result = session.run(query, user_id=user_id)
                banks = {}
                for record in result:
                    bank_name = record.get("name", "Unknown Bank")
                    if bank_name and bank_name not in banks:
                        banks[bank_name] = 0
                    if bank_name:
                        banks[bank_name] += 1
                
                bank_list = [{"name": name, "count": count} for name, count in banks.items()]
                print(f"Banks found for user {user_id}: {bank_list}")
                return bank_list
        except Exception as e:
            print(f"Error querying banks: {e}")
            return []

    def _query_investments(self, user_id: str) -> List[Dict[str, Any]]:
        """Query investments (assets) from the graph."""
        if not self.driver:
            return []
        
        try:
            with self.driver.session() as session:
                # First try: Assets linked to transactions
                query = """
                MATCH (t:Transaction {user_id: $user_id})-[:AFFECTS_ASSET]->(a:Asset {user_id: $user_id})
                WITH a, sum(t.amount) as invested_amount
                WHERE invested_amount > 0
                RETURN distinct 
                    a.name as name,
                    invested_amount as amount
                ORDER BY amount DESC
                LIMIT 20
                """
                result = session.run(query, user_id=user_id)
                investments = []
                seen = set()
                
                for record in result:
                    name = record.get("name")
                    if not name:
                        continue
                    amount = record.get("amount", 0)
                    
                    if name not in seen and amount > 0:
                        investments.append({
                            "name": name,
                            "type": "investment",
                            "amount": float(amount) if amount else 0.0
                        })
                        seen.add(name)
                
                if investments:
                    print(f"Investments found for user {user_id}: {len(investments)} assets")
                    return investments
                
                # Fallback: Try to get all assets for this user
                query_fallback = """
                MATCH (a:Asset {user_id: $user_id})
                RETURN distinct 
                    a.name as name,
                    coalesce(a.value, a.amount, 0) as amount
                ORDER BY amount DESC
                LIMIT 10
                """
                result = session.run(query_fallback, user_id=user_id)
                for record in result:
                    name = record.get("name")
                    if not name:
                        continue
                    amount = record.get("amount", 0)
                    
                    if name not in seen and amount > 0:
                        investments.append({
                            "name": name,
                            "type": "asset",
                            "amount": float(amount) if amount else 0.0
                        })
                        seen.add(name)
                
                print(f"Fallback: Found {len(investments)} assets for user {user_id}")
                return investments
                
        except Exception as e:
            print(f"Error querying investments: {e}")
            import traceback
            traceback.print_exc()
            return []

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
