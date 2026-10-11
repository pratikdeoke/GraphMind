"""
Mindmap Service - Retrieve graph structure for visualization
"""

from typing import List, Dict, Any, Tuple
from neo4j import GraphDatabase
from config.settings import Settings
from services.vector.milvus_service import get_milvus_service


class MindmapService:
    """
    Service to retrieve entire graph structure for a user.
    """

    def __init__(self):
        """Initialize Neo4j connection and Milvus service."""
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not connect to Neo4j: {e}")
            self.driver = None

        self.milvus_service = get_milvus_service()

    def get_user_graph(self, user_id: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Get all nodes and relationships for a user, including vector database entries.

        Args:
            user_id: User identifier

        Returns:
            Tuple of (nodes_list, edges_list)
        """
        if not self.driver:
            return [], []

        nodes = []
        edges = []

        try:
            with self.driver.session() as session:
                # Get all nodes for user (User node + all nodes with user_id)
                nodes_query = """
                MATCH (n)
                WHERE (n.user_id = $user_id OR (n:User AND n.id = $user_id))
                AND NOT 'RetrievalView' IN labels(n)
                AND NOT 'RankerFeedback' IN labels(n)
                RETURN 
                    elementId(n) as node_id,
                    labels(n) as labels,
                    properties(n) as properties
                """

                result = session.run(nodes_query, user_id=user_id)

                node_id_map = {}  # Map internal Neo4j IDs to our IDs

                for record in result:
                    neo4j_id = record["node_id"]
                    labels = record["labels"]
                    properties = dict(record["properties"])

                    # Get node type (first label)
                    node_type = labels[0] if labels else "Unknown"

                    # Get node ID or generate one
                    node_id = properties.get("id", f"node_{neo4j_id}")
                    node_id_map[neo4j_id] = node_id

                    # Create label for visualization
                    if node_type == "User":
                        label = properties.get(
                            "email", properties.get("id", "User"))
                    elif node_type == "Message":
                        text = properties.get("text", "")
                        label = text[:30] + "..." if len(text) > 30 else text
                    elif node_type == "Fact":
                        text = properties.get("text", "Fact")
                        label = text[:35] + "..." if len(text) > 35 else text
                    elif node_type == "Asset":
                        label = properties.get("name", "Asset")
                    elif node_type == "Goal":
                        label = properties.get("name", "Goal")
                    elif node_type == "Transaction":
                        amount = properties.get("amount", 0)
                        label = f"₹{amount:,.0f}" if amount else "Transaction"
                    else:
                        label = properties.get(
                            "name", properties.get("text", node_type))

                    nodes.append({
                        "id": node_id,
                        "type": node_type,
                        "label": label,
                        "properties": self._serialize_properties(properties)
                    })

                # Get all relationships for user (only edges between user's nodes)
                edges_query = """
                MATCH (a)-[r]->(b)
                WHERE ((a.user_id = $user_id OR (a:User AND a.id = $user_id))
                AND (b.user_id = $user_id OR (b:User AND b.id = $user_id)))
                AND NOT 'RetrievalView' IN labels(a)
                AND NOT 'RankerFeedback' IN labels(a)
                AND NOT 'RetrievalView' IN labels(b)
                AND NOT 'RankerFeedback' IN labels(b)
                RETURN 
                    elementId(r) as rel_id,
                    elementId(a) as source_id,
                    elementId(b) as target_id,
                    type(r) as rel_type,
                    properties(r) as properties
                """

                result = session.run(edges_query, user_id=user_id)

                for record in result:
                    rel_id = record["rel_id"]
                    source_neo4j_id = record["source_id"]
                    target_neo4j_id = record["target_id"]
                    rel_type = record["rel_type"]
                    properties = dict(record["properties"])

                    # Map Neo4j IDs to our node IDs
                    source_id = node_id_map.get(source_neo4j_id)
                    target_id = node_id_map.get(target_neo4j_id)

                    if source_id and target_id:
                        edges.append({
                            "id": f"edge_{rel_id}",
                            "source": source_id,
                            "target": target_id,
                            "type": rel_type,
                            "label": rel_type.replace("_", " ").title(),
                            "properties": self._serialize_properties(properties)
                        })

        except Exception as e:
            print(f"Error retrieving mindmap from Neo4j: {e}")

        # Add vector database entries as nodes
        try:
            if self.milvus_service:
                vectors = self.milvus_service.get_user_vectors(
                    user_id, limit=50)

                for idx, vector in enumerate(vectors):
                    vector_node_id = f"vec_{vector['vector_id']}"

                    # Create VectorEntry node
                    nodes.append({
                        "id": vector_node_id,
                        "type": "VectorEntry",
                        "label": vector['text'][:40] + "..." if len(vector['text']) > 40 else vector['text'],
                        "properties": {
                            "vector_id": vector['vector_id'],
                            "text": vector['text'],
                            "source_type": vector['source_type'],
                            "confidence": float(vector['confidence']),
                            "chunk_index": int(vector['chunk_index']),
                            "timestamp": vector['timestamp'],
                            "metadata": vector['metadata']
                        }
                    })

                    # Create edge from User to VectorEntry
                    user_node_id = next(
                        (n['id'] for n in nodes if n['type'] == 'User'), None)
                    if user_node_id:
                        edges.append({
                            "id": f"vec_edge_{vector['vector_id']}",
                            "source": user_node_id,
                            "target": vector_node_id,
                            "type": "OWNS_VECTOR",
                            "label": "OWNS_VECTOR",
                            "properties": {"source_type": vector['source_type']}
                        })

        except Exception as e:
            print(f"Error adding vector entries to mindmap: {e}")

        return nodes, edges

    def delete_user_graph(self, user_id: str) -> Dict[str, Any]:
        """
        Delete all nodes and relationships for a user from Neo4j.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with deletion summary
        """
        if not self.driver:
            return {"success": False, "message": "Neo4j connection unavailable"}

        try:
            with self.driver.session() as session:
                # Delete all relationships and nodes for user
                delete_query = """
                MATCH (n)
                WHERE n.user_id = $user_id OR (n:User AND n.id = $user_id)
                DETACH DELETE n
                RETURN count(n) as deleted_nodes
                """

                result = session.run(delete_query, user_id=user_id)
                record = result.single()
                deleted_count = record["deleted_nodes"] if record else 0

                return {
                    "success": True,
                    "message": f"Deleted {deleted_count} nodes from knowledge graph",
                    "deleted_nodes": deleted_count
                }

        except Exception as e:
            print(f"Error deleting user graph: {e}")
            return {
                "success": False,
                "message": f"Error deleting knowledge graph: {str(e)}",
                "deleted_nodes": 0
            }

    def delete_user_vectors(self, user_id: str) -> Dict[str, Any]:
        """
        Delete all vector entries for a user from Milvus.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with deletion summary
        """
        if not self.milvus_service:
            return {"success": False, "message": "Milvus service unavailable"}

        try:
            # Get count before deletion
            count_before = self.milvus_service.get_user_vectors_count(user_id)

            # Delete vectors
            success = self.milvus_service.delete_user_vectors(user_id)

            if success:
                return {
                    "success": True,
                    "message": f"Deleted {count_before} vectors from Milvus",
                    "deleted_vectors": count_before
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to delete vectors from Milvus",
                    "deleted_vectors": 0
                }
        except Exception as e:
            print(f"Error deleting user vectors: {e}")
            return {
                "success": False,
                "message": f"Error deleting vectors: {str(e)}",
                "deleted_vectors": 0
            }

    def get_user_vectors(self, user_id: str, limit: int = 100) -> List[Dict]:
        """
        Get all vector entries for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of vectors to return

        Returns:
            List of vector entry dictionaries
        """
        if not self.milvus_service:
            return []

        try:
            vectors = self.milvus_service.get_user_vectors(
                user_id, limit=limit)
            return vectors
        except Exception as e:
            print(f"Error retrieving user vectors: {e}")
            return []

    def _serialize_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize Neo4j types to JSON-compatible format."""
        from neo4j.time import DateTime
        import numpy as np

        serialized = {}
        for key, value in properties.items():
            if isinstance(value, DateTime):
                serialized[key] = value.isoformat()
            elif isinstance(value, (dict, list)):
                serialized[key] = str(value)
            elif isinstance(value, np.generic):
                serialized[key] = value.item()
            else:
                serialized[key] = value

        return serialized

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()


# Global instance
mindmap_service = MindmapService()
