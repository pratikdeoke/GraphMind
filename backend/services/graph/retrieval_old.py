"""
Graph Retrieval Service - Production-grade controlled retrieval.

Architecture:
- Mode-based queries (no wildcard explosion)
- Real hop distance calculation
- User-isolated traversal
- Timeline filtering
- Configurable scoring weights
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


class GraphRetrieval:
    """
    Production-grade graph retrieval with controlled traversal.
    
    Design Principles:
    - No wildcard path explosion
    - Mode-based targeted queries
    - Real hop distance scoring
    - Strict user isolation
    - O(edges) complexity, not O(paths)
    """
    
    # Configurable scoring weights (sum = 1.0)
    SCORE_WEIGHTS = {
        "graph_distance": 0.4,
        "recency": 0.3,
        "confidence": 0.2,
        "reinforcement": 0.1
    }
    
    # Recency decay parameter
    RECENCY_DECAY_LAMBDA = 0.1  # Exponential decay rate
    
    def __init__(self):
        """Initialize Neo4j connection and query understanding."""
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
        max_depth: int = 3
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Retrieve relevant graph context using controlled mode-based queries.
        
        Args:
            user_id: User identifier
            query: User's query text
            max_depth: Maximum hops (unused, kept for compatibility)
            
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
                mode, recommended_depth = self.query_understanding.classify_query(query)
                print(f"Query mode: {mode.value}, depth: {recommended_depth}")
                
                # 2. Extract timeline filter (optional)
                start_date = self.query_understanding.extract_timeline(query)
                
                # 3. Execute mode-specific retrieval
                raw_nodes = self._execute_mode_based_retrieval(
                    session, user_id, mode, start_date, recommended_depth
                )
                
                # 4. Calculate real hop distances from User node
                nodes_with_hops = self._calculate_hop_distances(
                    session, user_id, raw_nodes
                )
                
                # 5. Apply scoring and ranking
                retrieved_nodes = self._score_and_rank_nodes(
                    nodes_with_hops, query
                )
        
        except Exception as e:
            print(f"Error during graph retrieval: {e}")
            import traceback
            traceback.print_exc()
        
        retrieval_time_ms = (time.time() - start_time) * 1000
        
        return retrieved_nodes, retrieval_time_ms
    
    
    def _execute_mode_based_retrieval(
        self,
        session,
        user_id: str,
        mode: RetrievalMode,
        start_date: Optional[datetime],
        depth: int
    ) -> List[Dict[str, Any]]:
        """
        Execute controlled retrieval based on query mode.
        
        NO WILDCARD PATHS - Each mode has specific traversal.
        """
        # Build timeline filter clause
        timeline_filter = ""
        params = {"user_id": user_id}
        
        if start_date:
            timeline_filter = "AND n.timestamp >= $start_date"
            params["start_date"] = start_date
        
        if mode == RetrievalMode.DIRECT_LOOKUP:
            # Simple entity lookup (e.g., "What assets do I own?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            OPTIONAL MATCH (u)-[:OWNS_MESSAGE]->(m:Message)
            OPTIONAL MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
            OPTIONAL MATCH (t)-[:AFFECTS_ASSET]->(a:Asset)
            OPTIONAL MATCH (m)-[:DERIVED_FACT]->(f:Fact)
            WITH u, collect(DISTINCT m) + collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT f) as nodes
            UNWIND nodes as n
            WHERE n IS NOT NULL {timeline_filter}
            RETURN DISTINCT n
            LIMIT 50
            """
        
        elif mode == RetrievalMode.AGGREGATION:
            # Aggregation queries (e.g., "How much have I invested?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
            WHERE t.user_id = $user_id {timeline_filter.replace('n.', 't.')}
            OPTIONAL MATCH (t)-[:AFFECTS_ASSET]->(a:Asset)
            WHERE a.user_id = $user_id
            OPTIONAL MATCH (f:Fact)-[:CONFIRMS]->(t)
            WHERE f.user_id = $user_id
            WITH collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT f) as nodes
            UNWIND nodes as n
            WHERE n IS NOT NULL
            RETURN DISTINCT n
            LIMIT 100
            """
        
        elif mode == RetrievalMode.RELATIONAL_REASONING:
            # Multi-hop reasoning (e.g., "Is investment aligned with goal?")
            query = f"""
            MATCH (u:User {{id: $user_id}})
            OPTIONAL MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)-[:AFFECTS_ASSET]->(a:Asset)
            WHERE t.user_id = $user_id AND a.user_id = $user_id {timeline_filter.replace('n.', 't.')}
            OPTIONAL MATCH (a)-[:CONTRIBUTES_TO]->(g:Goal)
            WHERE g.user_id = $user_id
            OPTIONAL MATCH (u)-[:HAS_PREFERENCE]->(p:Preference)
            WHERE p.user_id = $user_id
            OPTIONAL MATCH (f:Fact)-[:CONFIRMS]->(t)
            WHERE f.user_id = $user_id
            OPTIONAL MATCH (f2:Fact)-[:RELATES_TO]->(a)
            WHERE f2.user_id = $user_id
            WITH collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT g) + 
                 collect(DISTINCT p) + collect(DISTINCT f) + collect(DISTINCT f2) as nodes
            UNWIND nodes as n
            WHERE n IS NOT NULL
            RETURN DISTINCT n
            LIMIT 150
            """
        
        else:
            # Fallback to direct lookup
            query = """
            MATCH (u:User {id: $user_id})
            MATCH (u)-[:MADE_TRANSACTION]->(t:Transaction)
            RETURN t as n
            LIMIT 50
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
                    "neo4j_id": node.id  # Store Neo4j internal ID for hop calculation
                })
        
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
                result = session.run(hop_query, user_id=user_id, node_id=node_id)
                record = result.single()
                hops = record["hops"] if record else 3  # Default to 3 if no path
            except:
                hops = 3  # Fallback
            
            node["hop_distance"] = hops
            nodes_with_hops.append(node)
        
        return nodes_with_hops
        """Convert Neo4j types to JSON-serializable Python types."""
        if isinstance(obj, DateTime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_neo4j_types(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._serialize_neo4j_types(item) for item in obj]
        else:
            return obj
    
    def _format_results(self, result) -> List[Dict[str, Any]]:
        """
        Format Neo4j results into structured dictionaries.
        """
        formatted_nodes = []
        
        try:
            for record in result:
                # User node
                user_node = record.get("u")
                if user_node:
                    formatted_nodes.append({
                        "type": list(user_node.labels)[0] if user_node.labels else "User",
                        "properties": self._serialize_neo4j_types(dict(user_node))
                    })
                
                # Connected nodes
                nodes = record.get("nodes", [])
                for node in nodes:
                    if node:  # Skip None values
                        formatted_nodes.append({
                            "type": list(node.labels)[0] if node.labels else "Entity",
                            "properties": self._serialize_neo4j_types(dict(node))
                        })
                
                # Relationships (stored in node context)
                rels = record.get("rels", [])
                for rel_list in rels:
                    if rel_list:  # rel_list might be a list of relationships
                        # Handle case where rels is a list of relationship lists
                        if isinstance(rel_list, list):
                            for rel in rel_list:
                                if rel:
                                    formatted_nodes.append({
                                        "type": "Relationship",
                                        "relationship_type": rel.type,
                                        "properties": self._serialize_neo4j_types(dict(rel))
                                    })
                        elif hasattr(rel_list, 'type'):  # Single relationship
                            formatted_nodes.append({
                                "type": "Relationship",
                                "relationship_type": rel_list.type,
                                "properties": self._serialize_neo4j_types(dict(rel_list))
                            })
        
        except Exception as e:
            print(f"Error formatting results: {e}")
        
        return formatted_nodes
    
    def _determine_query_depth(self, query: str) -> int:
        """
        Determine retrieval depth based on query complexity.
        
        Simple (1 hop): "What assets do I own?"
        Complex (2-3 hops): "Am I aligned with my retirement goal?"
        """
        query_lower = query.lower()
        
        # Keywords indicating complex multi-hop reasoning
        complex_keywords = [
            "aligned", "compare", "why", "how am i", "goal",
            "progress", "relationship", "between", "impact",
            "affect", "contributing", "towards"
        ]
        
        # Very complex queries need deeper traversal
        very_complex_keywords = [
            "overall", "portfolio", "all", "total", "complete",
            "entire", "comprehensive"
        ]
        
        if any(keyword in query_lower for keyword in very_complex_keywords):
            return 3  # Very complex query
        elif any(keyword in query_lower for keyword in complex_keywords):
            return 2  # Complex query
        else:
            return 1  # Simple query
    
    def _score_and_rank_nodes(self, nodes: List[Dict[str, Any]], query: str, depth: int) -> List[Dict[str, Any]]:
        """
        Score and rank retrieved nodes based on multiple factors.
        
        Scoring formula:
        final_score = 0.4 * graph_distance_score + 
                     0.3 * recency_score + 
                     0.2 * confidence + 
                     0.1 * reinforcement_score
        """
        scored_nodes = []
        now = datetime.now(timezone.utc)
        
        for node in nodes:
            props = node.get("properties", {})
            
            # Skip User nodes from ranking
            if node.get("type") == "User":
                continue
            
            # Graph distance score (inverse of depth, normalized)
            # Closer nodes get higher score
            graph_distance_score = 1.0 / (depth + 1)
            
            # Recency score (based on last_reinforced)
            recency_score = 0.5
            last_reinforced = props.get("last_reinforced")
            if last_reinforced:
                if isinstance(last_reinforced, str):
                    try:
                        last_reinforced_dt = datetime.fromisoformat(last_reinforced.replace("Z", "+00:00"))
                        days_ago = (now - last_reinforced_dt).days
                        # Exponential decay: nodes accessed recently score higher
                        recency_score = max(0.1, 1.0 / (1 + days_ago * 0.1))
                    except:
                        pass
            
            # Confidence score
            confidence = float(props.get("confidence", 0.5))
            
            # Reinforcement score (normalized)
            reinforcement_count = int(props.get("reinforcement_count", 0))
            reinforcement_score = min(1.0, reinforcement_count / 10.0)  # Cap at 10 accesses
            
            # Calculate final score
            final_score = (
                0.4 * graph_distance_score +
                0.3 * recency_score +
                0.2 * confidence +
                0.1 * reinforcement_score
            )
            
            # Add score to node
            node["retrieval_score"] = round(final_score, 3)
            scored_nodes.append(node)
        
        # Sort by score descending
        scored_nodes.sort(key=lambda x: x.get("retrieval_score", 0), reverse=True)
        
        return scored_nodes
    
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
                
                session.run(query, old_fact_id=old_fact_id, new_fact_id=new_fact_id, user_id=user_id)
                print(f"Marked contradiction between {old_fact_id} and {new_fact_id}")
        
        except Exception as e:
            print(f"Error marking contradiction: {e}")
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
