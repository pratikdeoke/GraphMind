"""Vector ingestion and retrieval using Neo4j-backed chunk storage."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import importlib
import math
import time
import uuid

from config.settings import Settings
from services.vector.embeddings import EmbeddingService


class VectorRetrieval:
    """Stores and searches text chunks for semantic retrieval."""

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.collection = Settings.MILVUS_COLLECTION
        self.driver = None

        try:
            neo4j_module = importlib.import_module("neo4j")
            GraphDatabase = getattr(neo4j_module, "GraphDatabase")
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
        except Exception as error:
            print(f"Warning: Vector retrieval driver unavailable: {error}")
            self.driver = None

    def ingest_message(
        self,
        user_id: str,
        message_text: str,
        related_node_ids: Optional[List[str]] = None,
        chunk_size: int = 450,
        overlap: int = 60
    ) -> int:
        """Chunk message, embed chunks, and persist to Neo4j."""
        if not self.driver:
            return 0

        chunks = self._chunk_text(
            message_text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            return 0

        related_node_ids = [node_id for node_id in (
            related_node_ids or []) if node_id]
        indexed_count = 0

        try:
            with self.driver.session() as session:
                session.run("MERGE (u:User {id: $user_id})", user_id=user_id)

                for index, chunk_text in enumerate(chunks):
                    vector = self.embedding_service.embed_text(chunk_text)
                    chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"

                    session.run(
                        """
                        MATCH (u:User {id: $user_id})
                        CREATE (c:DocumentChunk {
                            id: $chunk_id,
                            user_id: $user_id,
                            text: $text,
                            chunk_index: $chunk_index,
                            source_type: "chat",
                            embedding: $embedding,
                            embedding_id: $embedding_id,
                            confidence: 0.7,
                            timestamp: datetime(),
                            created_at: datetime(),
                            updated_at: datetime()
                        })
                        CREATE (u)-[:OWNS_CHUNK]->(c)
                        """,
                        user_id=user_id,
                        chunk_id=chunk_id,
                        text=chunk_text,
                        chunk_index=index,
                        embedding=vector,
                        embedding_id=f"{self.collection}:{chunk_id}"
                    )

                    for node_id in related_node_ids:
                        session.run(
                            """
                            MATCH (c:DocumentChunk {id: $chunk_id, user_id: $user_id})
                            MATCH (n {id: $node_id, user_id: $user_id})
                            MERGE (c)-[:MENTIONS]->(n)
                            """,
                            chunk_id=chunk_id,
                            node_id=node_id,
                            user_id=user_id
                        )

                    indexed_count += 1

        except Exception as error:
            print(f"Error during vector ingestion: {error}")

        return indexed_count

    def search(
        self,
        user_id: str,
        query: str,
        top_k: Optional[int] = None,
        candidate_limit: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Search user chunks by cosine similarity with adaptive thresholding.

        Optimizations:
        - Dynamic threshold based on top results
        - Better scoring normalization
        - Reduced candidate scanning for speed
        - Enhanced result metadata
        """
        if not self.driver:
            return [], 0.0

        start_time = time.time()
        top_k = top_k or Settings.VECTOR_TOP_K
        # Reduce candidate limit for faster retrieval (from 1000 to 200)
        candidate_limit = candidate_limit or min(
            Settings.VECTOR_CANDIDATE_LIMIT, 200)

        query_vector = self.embedding_service.embed_query(query)
        if not query_vector or not any(query_vector):
            return [], 0.0

        candidates: List[Dict[str, Any]] = []

        try:
            with self.driver.session() as session:
                # Optimized query: reduce candidates, improve filtering
                records = session.run(
                    """
                    MATCH (c:DocumentChunk {user_id: $user_id})
                    RETURN c.id as id,
                           c.text as text,
                           c.embedding as embedding,
                           c.timestamp as timestamp,
                           c.chunk_index as chunk_index
                    ORDER BY c.timestamp DESC
                    LIMIT $candidate_limit
                    """,
                    user_id=user_id,
                    candidate_limit=candidate_limit
                )

                for row in records:
                    embedding = row.get("embedding") or []
                    if not embedding:
                        continue

                    score = self._cosine_similarity(
                        query_vector, [float(v) for v in embedding])

                    # Dynamic threshold: collect all candidates, then filter
                    candidates.append(
                        {
                            "id": row.get("id"),
                            "text": row.get("text", ""),
                            "similarity": round(score, 4),
                            "retrieval_score": round(score, 4),
                            "timestamp": self._to_iso(row.get("timestamp")),
                            "chunk_index": row.get("chunk_index", 0),
                            "source": "vector"
                        }
                    )

        except Exception as error:
            print(f"Error during vector search: {error}")
            return [], 0.0

        # Sort by similarity (highest first)
        candidates.sort(key=lambda item: item.get(
            "similarity", 0.0), reverse=True)

        # Apply dynamic threshold: keep top results above 0.3, or at least top 3
        filtered_candidates = []
        for idx, cand in enumerate(candidates):
            if cand.get("similarity", 0.0) >= 0.3 or idx < 3:
                filtered_candidates.append(cand)
            elif idx >= top_k:
                break

        elapsed_ms = (time.time() - start_time) * 1000
        return filtered_candidates[:top_k], elapsed_ms

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Split text into overlapping chunks by word count."""
        words = [word for word in (text or "").split() if word]
        if not words:
            return []

        if len(words) <= chunk_size:
            return [" ".join(words)]

        step = max(1, chunk_size - overlap)
        chunks = []
        for start in range(0, len(words), step):
            end = start + chunk_size
            chunk_words = words[start:end]
            if not chunk_words:
                continue
            chunks.append(" ".join(chunk_words))
            if end >= len(words):
                break
        return chunks

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity for vectors of same dimension."""
        if not a or not b:
            return 0.0

        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a = a[:min_len]
            b = b[:min_len]

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    @staticmethod
    def _to_iso(value: Any) -> Optional[str]:
        """Serialize datetime-like value."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def close(self):
        """Close underlying driver."""
        if self.driver:
            self.driver.close()
