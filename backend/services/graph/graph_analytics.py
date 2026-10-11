"""
Graph Analytics Service - Compute PageRank and centrality metrics for better node ranking.

Provides:
- PageRank scoring for importance
- Betweenness centrality for bridge nodes
- Closeness centrality for connectivity
- Community detection for related clusters
"""

from typing import Dict, List, Any, Tuple
from neo4j import GraphDatabase
from config.settings import Settings


class GraphAnalytics:
    """
    Computes graph-based metrics for node importance and ranking.
    
    Key metrics:
    - PageRank: Importance based on incoming relationships
    - Betweenness Centrality: How often node appears in shortest paths
    - Closeness Centrality: Average distance to all other nodes
    - Community Membership: Which cluster does node belong to
    """
    
    def __init__(self):
        """Initialize Neo4j connection."""
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not connect to Neo4j: {e}")
            self.driver = None
    
    def compute_pagerank(self, user_id: str, max_iterations: int = 20) -> Dict[str, float]:
        """
        Compute PageRank for all nodes in user's subgraph.
        
        PageRank (0-1): How important is this node? Based on incoming edges.
        
        Args:
            user_id: User identifier
            max_iterations: Number of iterations for convergence
            
        Returns:
            Dictionary mapping node_id -> pagerank_score
        """
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                # Use Neo4j's built-in PageRank algorithm (requires GDS plugin)
                query = """
                MATCH (u:User {id: $user_id})
                CALL apoc.algo.pageRank(
                    'MATCH (n)-[r]-(m) WHERE n.user_id = $user_id AND m.user_id = $user_id RETURN id(n) as id, id(m) as id UNION ALL MATCH (u:User {id: $user_id})-[r]-(m) WHERE m.user_id = $user_id RETURN id(u) as id, id(m) as id',
                    'rel:>|<',
                    {iterations: $max_iterations, dampingFactor: 0.85}
                ) YIELD node, score
                RETURN node.id as node_id, score as pagerank LIMIT 1000
                """
                
                result = session.run(query, user_id=user_id, max_iterations=max_iterations)
                pagerank_scores = {}
                
                for record in result:
                    node_id = record.get("node_id")
                    score = record.get("pagerank", 0.0)
                    if node_id:
                        pagerank_scores[node_id] = float(score)
                
                # Normalize to 0-1 range
                if pagerank_scores:
                    max_score = max(pagerank_scores.values())
                    if max_score > 0:
                        pagerank_scores = {k: v / max_score for k, v in pagerank_scores.items()}
                
                print(f"[Analytics] Computed PageRank for {len(pagerank_scores)} nodes")
                return pagerank_scores
        
        except Exception as e:
            print(f"PageRank computation error (falling back): {e}")
            # Fallback: use simple incoming edge count
            return self._fallback_pagerank(user_id)
    
    def _fallback_pagerank(self, user_id: str) -> Dict[str, float]:
        """Fallback PageRank using incoming relationship count."""
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                query = """
                MATCH (n {user_id: $user_id})--(m {user_id: $user_id})
                WITH n, count(m) as incoming_count
                RETURN n.id as node_id, 
                       min(1.0, log(1 + incoming_count) / log(10)) as score
                """
                
                result = session.run(query, user_id=user_id)
                scores = {}
                
                for record in result:
                    node_id = record.get("node_id")
                    score = record.get("score", 0.0)
                    if node_id:
                        scores[node_id] = float(score)
                
                return scores
        
        except Exception as e:
            print(f"Fallback PageRank error: {e}")
            return {}
    
    def compute_betweenness_centrality(self, user_id: str) -> Dict[str, float]:
        """
        Compute betweenness centrality for nodes.
        
        Betweenness (0-1): How often does this node appear in shortest paths?
        High value = bridge node connecting different parts of graph
        
        Args:
            user_id: User identifier
            
        Returns:
            Dictionary mapping node_id -> centrality_score
        """
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                # Count how many shortest paths go through each node
                query = """
                MATCH (u:User {id: $user_id})
                WITH u
                MATCH (n {user_id: $user_id})
                WHERE n <> u
                MATCH (other {user_id: $user_id})
                WHERE other <> n AND other <> u
                MATCH path = shortestPath((n)-[*0..5]-(other))
                WITH n, count(DISTINCT path) as path_count
                RETURN n.id as node_id, 
                       min(1.0, log(1 + path_count) / log(100)) as betweenness
                """
                
                result = session.run(query, user_id=user_id)
                scores = {}
                
                for record in result:
                    node_id = record.get("node_id")
                    score = record.get("betweenness", 0.0)
                    if node_id:
                        scores[node_id] = float(score)
                
                print(f"[Analytics] Computed betweenness centrality for {len(scores)} nodes")
                return scores
        
        except Exception as e:
            print(f"Betweenness centrality error: {e}")
            return {}
    
    def compute_closeness_centrality(self, user_id: str) -> Dict[str, float]:
        """
        Compute closeness centrality for nodes.
        
        Closeness (0-1): How close is this node to all other nodes on average?
        High value = well-connected to most of graph
        
        Args:
            user_id: User identifier
            
        Returns:
            Dictionary mapping node_id -> centrality_score
        """
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                # Calculate average distance to all other nodes
                query = """
                MATCH (n {user_id: $user_id})
                MATCH (other {user_id: $user_id})
                WHERE n <> other
                OPTIONAL MATCH path = shortestPath((n)-[*1..5]-(other))
                WITH n, 
                     count(DISTINCT other) as total_nodes,
                     avg(CASE WHEN path IS NOT NULL THEN length(path) ELSE 5 END) as avg_distance
                RETURN n.id as node_id, 
                       1.0 / (avg_distance + 1) as closeness
                """
                
                result = session.run(query, user_id=user_id)
                scores = {}
                
                for record in result:
                    node_id = record.get("node_id")
                    score = record.get("closeness", 0.0)
                    if node_id:
                        scores[node_id] = float(score)
                
                # Normalize
                if scores:
                    max_score = max(scores.values())
                    if max_score > 0:
                        scores = {k: v / max_score for k, v in scores.items()}
                
                print(f"[Analytics] Computed closeness centrality for {len(scores)} nodes")
                return scores
        
        except Exception as e:
            print(f"Closeness centrality error: {e}")
            return {}
    
    def get_centrality_composite(self, user_id: str) -> Dict[str, float]:
        """
        Compute composite centrality score combining PageRank, betweenness, and closeness.
        
        Returns single score per node (0-1) representing overall importance.
        """
        pagerank = self.compute_pagerank(user_id)
        betweenness = self.compute_betweenness_centrality(user_id)
        closeness = self.compute_closeness_centrality(user_id)
        
        # Combine with equal weights
        composite = {}
        all_nodes = set(pagerank.keys()) | set(betweenness.keys()) | set(closeness.keys())
        
        for node_id in all_nodes:
            pr = pagerank.get(node_id, 0.0)
            be = betweenness.get(node_id, 0.0)
            cl = closeness.get(node_id, 0.0)
            
            # Average the three metrics
            composite[node_id] = (pr + be + cl) / 3.0
        
        print(f"[Analytics] Composite centrality computed for {len(composite)} nodes")
        return composite
    
    def detect_communities(self, user_id: str) -> Dict[str, int]:
        """
        Detect communities (clusters) in user's subgraph.
        
        Returns mapping of node_id -> community_id
        """
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                # Use Louvain algorithm if available (requires GDS)
                query = """
                MATCH (u:User {id: $user_id})
                CALL apoc.algo.louvain(
                    'MATCH (n {user_id: $user_id})-[r]-(m {user_id: $user_id}) RETURN id(n) as id, id(m) as id',
                    'both',
                    {iterations: 20}
                ) YIELD nodeId, clusterNo
                MATCH (n) WHERE id(n) = nodeId
                RETURN n.id as node_id, clusterNo as community_id
                """
                
                result = session.run(query, user_id=user_id)
                communities = {}
                
                for record in result:
                    node_id = record.get("node_id")
                    community = record.get("community_id")
                    if node_id:
                        communities[node_id] = int(community)
                
                print(f"[Analytics] Detected {len(set(communities.values()))} communities")
                return communities
        
        except Exception as e:
            print(f"Community detection error: {e}")
            return {}
