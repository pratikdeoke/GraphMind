"""
Memory Orchestrator - Coordinates memory ingestion workflow.

Flow:
1. Extract entities from text (LLM)
2. Ingest into graph (Neo4j)
3. Ingest into vector database (Milvus)
"""

from typing import Dict, Any
from services.extraction.llm_extractor import LLMExtractor
from services.graph.ingestion import GraphIngestion
from services.graph.entity_finalizer import EntityFinalizer
from services.vector.retrieval import VectorRetrieval
from services.vector.milvus_service import get_milvus_service
from services.cache.retrieval_cache import get_retrieval_cache


class MemoryOrchestrator:
    """
    Orchestrates complete memory ingestion workflow.
    """

    def __init__(self):
        """Initialize all required services."""
        self.extractor = LLMExtractor()
        self.graph_ingestion = GraphIngestion()
        self.entity_finalizer = EntityFinalizer()
        self.vector_retrieval = VectorRetrieval()
        self.milvus_service = get_milvus_service()

    def ingest_memory(self, user_id: str, message: str, source_type: str = "chat") -> Dict[str, Any]:
        """
        Execute complete memory ingestion workflow.

        Args:
            user_id: User identifier
            message: User's message containing information to store
            source_type: Source type for the message ('chat' or 'document')

        Returns:
            Dictionary with ingestion results
        """
        # Step 1: Extract structured data from text
        extracted_data = self.extractor.extract(message, user_id)
        facts = extracted_data.get("facts", [])
        nodes = extracted_data.get("nodes", [])
        relationships = extracted_data.get("relationships", [])

        # Step 2: Ingest into graph (Message + Facts + Entities)
        # Documents are bulk-imported reference data, not conversational claims,
        # so we skip the naive contradiction heuristic for them (per README).
        skip_contradiction = (source_type == "document")
        graph_result = self.graph_ingestion.ingest_memory(
            user_id=user_id,
            message_text=message,
            facts=facts,
            nodes=nodes,
            relationships=relationships,
            skip_contradiction_detection=skip_contradiction,
            source_type=source_type
        )

        # Step 2.5: Finalize graph features for retrieval quality (degree, canonical names).
        finalizer_result = self.entity_finalizer.finalize_user_graph(user_id)

        # Step 3: Ingest vector chunks for semantic retrieval
        related_node_ids = []
        for fact in facts:
            fact_id = fact.get("id")
            if fact_id:
                related_node_ids.append(fact_id)
        for node in nodes:
            node_id = node.get("properties", {}).get("id")
            if node_id:
                related_node_ids.append(node_id)

        chunks_indexed = self.vector_retrieval.ingest_message(
            user_id=user_id,
            message_text=message,
            related_node_ids=list(set(related_node_ids))
        )

        # Step 4: Ingest into Milvus vector database
        vector_ids_indexed = 0
        if self.milvus_service:
            try:
                # Use VectorRetrieval's chunking
                chunks = self.vector_retrieval._chunk_text(
                    message, chunk_size=450, overlap=60)

                if chunks:
                    fact_ids = [f.get("id") for f in facts if f.get("id")]
                    fact_texts = [f.get("text") for f in facts if f.get("text")]
                    batch_data = [
                        {
                            "text": chunk,
                            "chunk_index": idx,
                            "source_type": source_type,
                            "confidence": 0.7,
                            "metadata": {
                                "facts": fact_ids,
                                "fact_texts": fact_texts,
                            },
                        }
                        for idx, chunk in enumerate(chunks)
                    ]
                    vector_ids = self.milvus_service.ingest_batch(
                        user_id, batch_data)
                    vector_ids_indexed = len(vector_ids)
            except Exception as e:
                print(f"Warning: Milvus ingestion failed: {e}")

        # Step 5: Invalidate retrieval cache for this user
        # This ensures stale context isn't returned on next query
        cache = get_retrieval_cache()
        if cache:
            cache.invalidate_user(user_id)

        return {
            "nodes_created": graph_result.get("nodes_created", 0),
            "relationships_created": graph_result.get("relationships_created", 0),
            "facts_created": graph_result.get("facts_created", 0),
            "chunks_indexed": chunks_indexed,
            "vectors_indexed": vector_ids_indexed,
            "finalizer_nodes_updated": finalizer_result.get("finalizer_nodes_updated", 0),
            "finalizer_relationships_updated": finalizer_result.get("finalizer_relationships_updated", 0),
            "finalizer_views_updated": finalizer_result.get("finalizer_views_updated", 0),
        }

    def _chunk_text(self, text: str, chunk_size: int = 450, overlap: int = 60) -> list:
        """Split text into overlapping chunks."""
        if not text or chunk_size <= 0:
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunks.append(text[start:end])
            start = end - overlap if end < text_len else text_len

        return chunks

    def close(self):
        """Close all service connections."""
        self.graph_ingestion.close()
        self.entity_finalizer.close()
        self.vector_retrieval.close()
        if self.milvus_service:
            self.milvus_service.close()
