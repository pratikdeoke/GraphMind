"""Milvus vector database integration for semantic vector storage and retrieval."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import uuid
import json

from pymilvus import Collection, connections, utility, FieldSchema, CollectionSchema, DataType
from config.settings import Settings
from services.vector.embeddings import EmbeddingService


class MilvusService:
    """Milvus vector database service for embeddings storage and semantic search."""

    def __init__(self):
        """Initialize Milvus connection and collection."""
        self.embedding_service = EmbeddingService()
        self.collection_name = Settings.MILVUS_COLLECTION
        self.embedding_dim = Settings.EMBEDDING_DIMENSION
        self.collection: Optional[Collection] = None

        try:
            # Connect to Milvus
            connections.connect(
                alias="default",
                host=Settings.MILVUS_HOST,
                port=int(Settings.MILVUS_PORT),
                timeout=30
            )

            # Create or load collection
            self._setup_collection()
        except Exception as error:
            print(f"Warning: Milvus connection failed: {error}")
            self.collection = None

    def _setup_collection(self):
        """Create collection if not exists, or load existing collection."""
        try:
            # Check if collection exists
            if utility.has_collection(self.collection_name):
                self.collection = Collection(self.collection_name)
                self.collection.load()
            else:
                # Define schema
                fields = [
                    FieldSchema(name="id", dtype=DataType.VARCHAR,
                                max_length=100, is_primary=True),
                    FieldSchema(name="user_id",
                                dtype=DataType.VARCHAR, max_length=100),
                    FieldSchema(name="text", dtype=DataType.VARCHAR,
                                max_length=65535),
                    FieldSchema(
                        name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
                    FieldSchema(name="chunk_index", dtype=DataType.INT32),
                    FieldSchema(name="source_type",
                                dtype=DataType.VARCHAR, max_length=50),
                    FieldSchema(name="confidence", dtype=DataType.FLOAT),
                    FieldSchema(name="timestamp",
                                dtype=DataType.VARCHAR, max_length=50),
                    FieldSchema(name="metadata",
                                dtype=DataType.VARCHAR, max_length=65535),
                ]

                schema = CollectionSchema(
                    fields, description=f"Vector storage for {self.collection_name}")
                self.collection = Collection(self.collection_name, schema)

                # Create index for vector field
                index_params = {
                    "index_type": "IVF_FLAT",
                    "metric_type": "L2",
                    "params": {"nlist": 128}
                }
                self.collection.create_index("embedding", index_params)
                self.collection.load()
        except Exception as error:
            print(f"Error setting up Milvus collection: {error}")
            self.collection = None

    def ingest_vector_chunk(
        self,
        user_id: str,
        text: str,
        chunk_index: int = 0,
        source_type: str = "chat",
        confidence: float = 0.7,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Ingest a text chunk with embedding into Milvus.

        Args:
            user_id: User identifier
            text: Text content to embed
            chunk_index: Index of this chunk (for multi-chunk documents)
            source_type: Source type (chat, document, etc.)
            confidence: Confidence score
            metadata: Additional metadata as dict

        Returns:
            Vector ID in Milvus
        """
        if not self.collection:
            return ""

        try:
            vector_id = f"vec_{uuid.uuid4().hex[:16]}"
            embedding = self.embedding_service.embed_text(text)

            now = datetime.utcnow().isoformat()
            metadata_str = json.dumps(metadata or {})

            # Insert into Milvus
            self.collection.insert([
                [vector_id],
                [user_id],
                [text],
                [embedding],
                [chunk_index],
                [source_type],
                [confidence],
                [now],
                [metadata_str]
            ])

            # Flush to ensure data is persisted
            self.collection.flush()

            return vector_id
        except Exception as error:
            print(f"Error ingesting vector chunk: {error}")
            return ""

    def ingest_batch(
        self,
        user_id: str,
        chunks: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Batch ingest multiple text chunks.

        Args:
            user_id: User identifier
            chunks: List of dicts with keys: text, chunk_index, source_type, confidence, metadata

        Returns:
            List of vector IDs
        """
        if not self.collection or not chunks:
            return []

        try:
            vector_ids = []
            texts = []
            embeddings = []
            chunk_indices = []
            source_types = []
            confidences = []
            timestamps = []
            metadatas = []
            user_ids = []

            now = datetime.utcnow().isoformat()

            for chunk in chunks:
                vector_id = f"vec_{uuid.uuid4().hex[:16]}"
                text = chunk.get("text", "")
                embedding = self.embedding_service.embed_text(text)

                vector_ids.append(vector_id)
                texts.append(text)
                embeddings.append(embedding)
                chunk_indices.append(chunk.get("chunk_index", 0))
                source_types.append(chunk.get("source_type", "chat"))
                confidences.append(chunk.get("confidence", 0.7))
                timestamps.append(now)
                metadatas.append(json.dumps(chunk.get("metadata", {})))
                user_ids.append(user_id)

            # Insert batch
            self.collection.insert([
                vector_ids,
                user_ids,
                texts,
                embeddings,
                chunk_indices,
                source_types,
                confidences,
                timestamps,
                metadatas
            ])

            # Flush to ensure data is persisted
            self.collection.flush()

            return vector_ids
        except Exception as error:
            print(f"Error batch ingesting vectors: {error}")
            return []

    def search_similar(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 5,
        threshold: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors in user's collection (optimized for sub-100ms).

        Args:
            user_id: User identifier
            query_text: Text to search for
            top_k: Number of top results (reduced for speed)
            threshold: Similarity threshold (0-1, lower is better for L2 distance)

        Returns:
            List of results with vector_id, text, distance, metadata
        """
        if not self.collection:
            return []

        try:
            # Embed query
            query_vector = self.embedding_service.embed_text(query_text)

            # Optimized search parameters for speed
            # nprobe: number of clusters to search (lower = faster but less accurate)
            search_params = {
                "metric_type": "L2",
                "params": {"nprobe": 8}  # Reduced from 10 for speed
            }
            results = self.collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=f'user_id == "{user_id}"',
                output_fields=["user_id", "text", "chunk_index",
                               "source_type", "confidence", "timestamp", "metadata"]
            )

            response = []
            for hits in results:
                for hit in hits:
                    distance = hit.distance
                    # For L2 distance, lower is better; convert to similarity (higher is better)
                    similarity = 1.0 / (1.0 + distance)

                    if similarity >= threshold:
                        entity = hit.entity
                        metadata = {}
                        try:
                            metadata = json.loads(entity.get("metadata", "{}"))
                        except:
                            pass

                        response.append({
                            "vector_id": hit.id,
                            "text": entity.get("text", ""),
                            "similarity": round(similarity, 4),
                            "distance": round(distance, 4),
                            "chunk_index": entity.get("chunk_index", 0),
                            "source_type": entity.get("source_type", ""),
                            "confidence": entity.get("confidence", 0.0),
                            "timestamp": entity.get("timestamp", ""),
                            "metadata": metadata
                        })

            return response
        except Exception as error:
            print(f"Error searching vectors: {error}")
            return []

    def delete_user_vectors(self, user_id: str) -> bool:
        """
        Delete all vectors for a user.

        Args:
            user_id: User identifier

        Returns:
            True if successful
        """
        if not self.collection:
            return False

        try:
            expr = f'user_id == "{user_id}"'
            self.collection.delete(expr)
            return True
        except Exception as error:
            print(f"Error deleting user vectors: {error}")
            return False

    def get_user_vectors_count(self, user_id: str) -> int:
        """
        Get count of vectors for a user.

        Args:
            user_id: User identifier

        Returns:
            Number of vectors
        """
        if not self.collection:
            return 0

        try:
            expr = f'user_id == "{user_id}"'
            # Use collection query instead of count
            results = self.collection.query(expr=expr, output_fields=["id"])
            return len(results)
        except Exception as error:
            print(f"Error counting user vectors: {error}")
            return 0

    def get_user_vectors(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all vectors for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of vectors to return

        Returns:
            List of vector records
        """
        if not self.collection:
            return []

        try:
            expr = f'user_id == "{user_id}"'
            results = self.collection.query(
                expr=expr,
                output_fields=["id", "text", "chunk_index", "source_type",
                               "confidence", "timestamp", "metadata"],
                limit=limit
            )

            response = []
            for record in results:
                metadata = {}
                try:
                    metadata = json.loads(record.get("metadata", "{}"))
                except:
                    pass

                response.append({
                    "vector_id": record.get("id", ""),
                    "text": record.get("text", ""),
                    "chunk_index": record.get("chunk_index", 0),
                    "source_type": record.get("source_type", ""),
                    "confidence": record.get("confidence", 0.0),
                    "timestamp": record.get("timestamp", ""),
                    "metadata": metadata
                })

            return response
        except Exception as error:
            print(f"Error retrieving user vectors: {error}")
            return []

    def close(self):
        """Close Milvus connection."""
        try:
            if self.collection:
                self.collection.flush()
            connections.disconnect(alias="default")
        except Exception as error:
            print(f"Error closing Milvus connection: {error}")


# Global instance
milvus_service: Optional[MilvusService] = None


def get_milvus_service() -> Optional[MilvusService]:
    """Get or create global Milvus service instance."""
    global milvus_service
    if milvus_service is None:
        milvus_service = MilvusService()
    return milvus_service
