from typing import Dict, Any, List, Tuple, Optional
import time
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from config.settings import Settings
from services.graph.retrieval import GraphRetrieval
from services.graph.query_decomposition import QueryDecomposition, QueryIntent
from services.graph.query_router import QueryRouter, RetrievalPlan, RetrievalStrategy
from services.graph.community_selector import DynamicCommunitySelector, CommunityCandidate
from services.graph.community_persistence import CommunityPersistence
from services.graph.hybrid_ranker import HybridRanker
from services.llm.answer_generator import AnswerGenerator
from services.vector.retrieval import VectorRetrieval
from services.vector.milvus_service import get_milvus_service
from services.cache.retrieval_cache import get_retrieval_cache


class RetrievalOrchestrator:
    """
    Orchestrates complete query retrieval and answer generation workflow.

    Optimized for sub-100ms retrieval through:
    - Parallel graph + vector retrieval
    - Reduced query complexity
    - Milvus vector search integration
    - Result caching (5-minute TTL)
    """

    RRF_K = 60
    MAX_RETRIEVAL_MS = 100  # Target: sub-100ms retrieval
    GLOBAL_MAP_BATCH_SIZE = 4
    DRIFT_MAX_DEPTH = 2
    DRIFT_MAX_FOLLOWUPS = 2

    def __init__(self):
        """Initialize all required services."""
        self.graph_retrieval = GraphRetrieval()
        self.vector_retrieval = VectorRetrieval()
        self.milvus_service = get_milvus_service()
        self.query_decomposition = QueryDecomposition()
        self.query_router = QueryRouter()
        self.community_selector = DynamicCommunitySelector()
        self.community_persistence = CommunityPersistence()
        self.hybrid_ranker = HybridRanker()
        self.answer_generator = AnswerGenerator()
        self.executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="retrieval_")
        self.cache = get_retrieval_cache()
        # Create event loop for async operations (lazy initialization)
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def retrieve_and_answer(
        self,
        user_id: str,
        query: str,
        strategy_override: Optional[str] = None,
        encryption_key: Optional[bytes] = None,
    ) -> Tuple[str, Dict[str, float], List[Dict[str, Any]]]:
        """
        Execute complete retrieval and answer generation workflow.

        Optimized pipeline:
        1. Check cache for recent results
        2. Parallel graph + vector retrieval (concurrent)
        3. Reciprocal rank fusion
        4. LLM answer generation
        5. Deferred node reinforcement

        Args:
            user_id: User identifier
            query: User's question

        Returns:
            Tuple of (answer, metrics, memory_citations)
        """
        retrieval_start = time.time()
        cache_hit = False

        # Step 0: Decompose and route query to a strategy plan.
        decomposition_start = time.time()
        decomposed = self.query_decomposition.decompose(query)
        decomposition_ms = (time.time() - decomposition_start) * 1000
        retrieval_plan = self.query_router.route(query, decomposed)
        override_strategy = self._parse_strategy_override(strategy_override)
        if override_strategy:
            retrieval_plan.strategy = override_strategy

        # Step 1: Check cache
        cached_results = self.cache.get(user_id, query, "retrieval_context")
        if cached_results:
            cache_hit = True
            graph_context = cached_results.get("graph_context", [])
            vector_context = cached_results.get("vector_context", [])
            graph_query_ms = 0.0  # From cache
            vector_search_ms = 0.0  # From cache
        else:
            # Step 2: Parallel retrieval using asyncio (graph + vector simultaneously)
            try:
                graph_context, vector_context, graph_query_ms, vector_search_ms = (
                    self._run_async_retrieval(user_id, query, retrieval_plan, encryption_key)
                )
            except Exception as e:
                # Fallback to sequential retrieval if async fails
                print(
                    f"Async retrieval failed, falling back to sequential: {e}")
                graph_context, graph_query_ms = self._retrieve_graph_parallel(
                    user_id, query, retrieval_plan, encryption_key)
                vector_context, vector_search_ms = self._retrieve_vector_parallel(
                    user_id, query, retrieval_plan)

            # Cache retrieval results
            self.cache.set(
                user_id, query,
                {
                    "graph_context": graph_context,
                    "vector_context": vector_context
                },
                "retrieval_context"
            )

        # Step 3: Assemble context with reciprocal rank fusion
        context_start = time.time()
        fused_results = self._fuse_rrf(graph_context, vector_context)
        ranker_start = time.time()
        ranked_results = self.hybrid_ranker.rank(
            user_id=user_id,
            strategy=retrieval_plan.strategy.value,
            fused_results=fused_results,
        )
        ranker_ms = (time.time() - ranker_start) * 1000

        # Step 2.5: Strategy-aware context selection.
        formatted_context, vector_context_formatted = self._select_context_by_strategy(
            ranked_results,
            retrieval_plan,
        )

        context_assembly_ms = (time.time() - context_start) * 1000

        # Step 4: Generate answer using LLM (with timing)
        llm_start = time.time()
        map_phase_ms = 0.0
        reduce_phase_ms = 0.0
        community_selection_ms = 0.0
        community_refresh_count = 0
        selected_communities = 0
        selected_community_ids: List[str] = []
        drift_expansion_ms = 0.0
        drift_iterations = 0
        drift_followups = 0
        if retrieval_plan.strategy == RetrievalStrategy.GLOBAL:
            (
                answer,
                map_phase_ms,
                reduce_phase_ms,
                community_selection_ms,
                community_refresh_count,
                selected_community_ids,
            ) = self._generate_global_answer_map_reduce(
                user_id=user_id,
                query=query,
                graph_context=formatted_context,
                vector_context=vector_context_formatted,
            )
            selected_communities = len(selected_community_ids)
        elif retrieval_plan.strategy == RetrievalStrategy.DRIFT:
            (
                answer,
                drift_expansion_ms,
                drift_iterations,
                drift_followups,
            ) = self._generate_drift_answer(
                user_id=user_id,
                query=query,
                retrieval_plan=retrieval_plan,
                seed_graph_context=formatted_context,
                seed_vector_context=vector_context_formatted,
            )
        else:
            answer = self.answer_generator.generate(
                query=query,
                graph_context=formatted_context,
                vector_context=vector_context_formatted
            )
        llm_generation_ms = (time.time() - llm_start) * 1000

        # Step 5: Assemble detailed metrics
        total_retrieval_ms = (time.time() - retrieval_start) * 1000
        retrieval_ms = graph_query_ms + vector_search_ms + context_assembly_ms

        metrics = {
            "decomposition_ms": round(decomposition_ms, 2),
            "retrieval_strategy": retrieval_plan.strategy.value,
            "strategy_override": strategy_override or "auto",
            "decomposition_confidence": round(decomposed.confidence, 3),
            "graph_top_k": retrieval_plan.graph_top_k,
            "vector_top_k": retrieval_plan.vector_top_k,
            "graph_query_ms": round(graph_query_ms, 2),
            "vector_search_ms": round(vector_search_ms, 2),
            "context_assembly_ms": round(context_assembly_ms, 2),
            "ranker_ms": round(ranker_ms, 2),
            "community_selection_ms": round(community_selection_ms, 2),
            "community_refresh_count": community_refresh_count,
            "selected_communities": selected_communities,
            "selected_community_ids": selected_community_ids,
            "map_phase_ms": round(map_phase_ms, 2),
            "reduce_phase_ms": round(reduce_phase_ms, 2),
            "drift_expansion_ms": round(drift_expansion_ms, 2),
            "drift_iterations": drift_iterations,
            "drift_followups": drift_followups,
            "retrieval_ms": round(retrieval_ms, 2),
            "total_retrieval_ms": round(total_retrieval_ms, 2),
            "llm_generation_ms": round(llm_generation_ms, 2),
            "retrieval_optimized": retrieval_ms < self.MAX_RETRIEVAL_MS,
            "cache_hit": cache_hit
        }

        # Step 6: Format memory citations with scores
        memory_citations = self._format_memory_citations(ranked_results, query)

        # Step 7: DEFERRED REINFORCEMENT - Update cited nodes after answer generation
        cited_node_ids = [node["properties"]["id"] for node in formatted_context[:10]
                          if "properties" in node and "id" in node["properties"]]
        if cited_node_ids:
            # Run reinforcement in background thread to avoid blocking
            self._reinforce_async(user_id, cited_node_ids)
            self.hybrid_ranker.update_feedback(user_id, cited_node_ids)

        return answer, metrics, memory_citations

    def _run_async_retrieval(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan,
        encryption_key: Optional[bytes] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, float]:
        """
        Run graph and vector retrieval in parallel using asyncio.

        Creates a new event loop and runs async parallel retrieval.

        Returns:
            Tuple of (graph_context, vector_context, graph_time_ms, vector_time_ms)
        """
        graph_future = self.executor.submit(
            self._retrieve_graph_sync,
            user_id,
            query,
            retrieval_plan,
            encryption_key,
        )
        vector_future = self.executor.submit(
            self._retrieve_vector_sync,
            user_id,
            query,
            retrieval_plan,
        )

        graph_context, graph_query_ms = graph_future.result()
        vector_context, vector_search_ms = vector_future.result()
        return graph_context, vector_context, graph_query_ms, vector_search_ms

    async def _async_parallel_retrieve(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, float]:
        """
        Async function to retrieve graph and vector context in parallel.

        Uses asyncio.gather to run both retrievals concurrently.
        Each retrieval runs in a thread pool executor to avoid blocking.

        Returns:
            Tuple of (graph_context, vector_context, graph_time_ms, vector_time_ms)
        """
        # Create tasks for parallel execution
        graph_task = asyncio.create_task(
            self._async_retrieve_graph(user_id, query, retrieval_plan)
        )
        vector_task = asyncio.create_task(
            self._async_retrieve_vector(user_id, query, retrieval_plan)
        )

        # Wait for both tasks to complete (true parallel execution)
        results = await asyncio.gather(graph_task, vector_task, return_exceptions=True)

        # Handle results
        if isinstance(results[0], Exception):
            print(f"Graph retrieval exception: {results[0]}")
            graph_context, graph_query_ms = [], 0.0
        else:
            graph_context, graph_query_ms = results[0]

        if isinstance(results[1], Exception):
            print(f"Vector retrieval exception: {results[1]}")
            vector_context, vector_search_ms = [], 0.0
        else:
            vector_context, vector_search_ms = results[1]

        return graph_context, vector_context, graph_query_ms, vector_search_ms

    async def _async_retrieve_graph(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Async wrapper for graph retrieval.

        Offloads blocking graph query to thread executor for non-blocking execution.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._retrieve_graph_sync,
            user_id,
            query,
            retrieval_plan
        )

    async def _async_retrieve_vector(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Async wrapper for vector retrieval.

        Offloads blocking vector search to thread executor for non-blocking execution.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._retrieve_vector_sync,
            user_id,
            query,
            retrieval_plan
        )

    def _retrieve_graph_sync(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan,
        encryption_key: Optional[bytes] = None,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Synchronous graph retrieval (executed in thread executor).

        This is the actual blocking operation that gets run in a thread.
        """
        start = time.time()
        try:
            graph_context, _ = self.graph_retrieval.retrieve(
                user_id=user_id,
                query=query,
                max_depth=retrieval_plan.graph_depth,
                top_k=retrieval_plan.graph_top_k,
                encryption_key=encryption_key,
            )
            elapsed = (time.time() - start) * 1000
            graph_context = graph_context[: retrieval_plan.graph_top_k]
            return graph_context, elapsed
        except Exception as e:
            print(f"Graph retrieval error: {e}")
            return [], (time.time() - start) * 1000

    def _retrieve_vector_sync(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Synchronous vector retrieval (executed in thread executor).

        This is the actual blocking operation that gets run in a thread.
        """
        start = time.time()
        try:
            if not retrieval_plan.enable_vector:
                return [], (time.time() - start) * 1000

            # Try Milvus first (faster for semantic search)
            if self.milvus_service and self.milvus_service.collection:
                vector_context = self._search_milvus(
                    user_id, query, top_k=retrieval_plan.vector_top_k
                )
                if vector_context:
                    elapsed = (time.time() - start) * 1000
                    return vector_context, elapsed

            # Fallback to Neo4j vector retrieval
            vector_context, _ = self.vector_retrieval.search(
                user_id=user_id,
                query=query,
                top_k=retrieval_plan.vector_top_k
            )
            elapsed = (time.time() - start) * 1000
            return vector_context, elapsed
        except Exception as e:
            print(f"Vector retrieval error: {e}")
            return [], (time.time() - start) * 1000

    def _retrieve_graph_parallel(self, user_id: str, query: str, retrieval_plan: RetrievalPlan, encryption_key: Optional[bytes] = None) -> Tuple[List[Dict[str, Any]], float]:
        """Fallback: Retrieve from graph database sequentially with optimized depth."""
        return self._retrieve_graph_sync(user_id, query, retrieval_plan, encryption_key)

    def _retrieve_vector_parallel(self, user_id: str, query: str, retrieval_plan: RetrievalPlan) -> Tuple[List[Dict[str, Any]], float]:
        """Fallback: Retrieve from vector database (Milvus) with fallback to Neo4j sequentially."""
        return self._retrieve_vector_sync(user_id, query, retrieval_plan)

    def _search_milvus(self, user_id: str, query: str, top_k: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Search Milvus for semantic vector matches."""
        try:
            results = self.milvus_service.search_similar(
                user_id=user_id,
                query_text=query,
                top_k=top_k,
                threshold=0.4  # Lower threshold for more results
            )

            if results:
                # Convert Milvus results to standard format
                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "id": result.get("vector_id", ""),
                        "text": result.get("text", ""),
                        "similarity": result.get("similarity", 0.0),
                        "retrieval_score": result.get("similarity", 0.0),
                        "source_type": result.get("source_type", "vector"),
                        "confidence": result.get("confidence", 0.7),
                        "metadata": result.get("metadata", {})
                    })
                return formatted_results
        except Exception as e:
            print(f"Milvus search error: {e}")

        return None

    def _reinforce_async(self, user_id: str, node_ids: List[str]) -> None:
        """Reinforce cited nodes in background thread."""
        try:
            self.executor.submit(
                self.graph_retrieval.reinforce_cited_nodes,
                user_id,
                node_ids
            )
        except Exception as e:
            print(f"Background reinforcement error: {e}")

    def _fuse_rrf(
        self,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Fuse graph and vector results using adaptive reciprocal rank fusion.

        Improvements:
        - Adaptive weighting based on confidence scores
        - Confidence-aware threshold filtering
        - Better score normalization
        - Deduplication of similar results

        Args:
            graph_context: Graph retrieval results
            vector_context: Vector retrieval results

        Returns:
            Sorted list of fused results
        """
        fused: List[Dict[str, Any]] = []

        # Adaptive weights based on result quality
        graph_confidence_avg = self._avg_confidence(graph_context)
        vector_confidence_avg = self._avg_confidence(vector_context)

        # Normalize weights (give more weight to higher-confidence source)
        total_confidence = graph_confidence_avg + vector_confidence_avg
        if total_confidence > 0:
            graph_weight = graph_confidence_avg / total_confidence
            vector_weight = vector_confidence_avg / total_confidence
        else:
            graph_weight = 0.5
            vector_weight = 0.5

        # Fuse graph results with adaptive weighting
        for rank, node in enumerate(graph_context, start=1):
            confidence = node.get("confidence", node.get(
                "properties", {}).get("confidence", 0.7))

            # Adaptive RRF: confidence modulates the RRF score
            base_rrf = 1.0 / (self.RRF_K + rank)
            confidence_boost = confidence * 0.3  # 0-0.3 boost based on confidence
            rrf_score = base_rrf * (1.0 + confidence_boost) * graph_weight

            fused.append(
                {
                    "source": "graph",
                    "payload": node,
                    "fusion_score": round(rrf_score, 6),
                    "rank": rank,
                    "source_weight": round(graph_weight, 3),
                    "confidence": round(confidence, 3)
                }
            )

        # Fuse vector results with adaptive weighting
        for rank, chunk in enumerate(vector_context, start=1):
            chunk["retrieval_score"] = chunk.get(
                "retrieval_score", chunk.get("similarity", 0.0))
            confidence = chunk.get("retrieval_score", 0.5)

            # Adaptive RRF: confidence modulates the RRF score
            base_rrf = 1.0 / (self.RRF_K + rank)
            confidence_boost = confidence * 0.3  # 0-0.3 boost based on similarity
            rrf_score = base_rrf * (1.0 + confidence_boost) * vector_weight

            fused.append(
                {
                    "source": "vector",
                    "payload": chunk,
                    "fusion_score": round(rrf_score, 6),
                    "rank": rank,
                    "source_weight": round(vector_weight, 3),
                    "confidence": round(confidence, 3)
                }
            )

        # Sort by fusion score (highest first)
        fused.sort(key=lambda item: item.get(
            "fusion_score", 0.0), reverse=True)

        # Keep a generous candidate pool. A single entity can appear as both a node
        # and a restating Fact, so we must NOT truncate aggressively here or distinct
        # entities (e.g. the 5th stock) get dropped before ranking/dedup can run.
        # Citation-level entity dedup downstream collapses the duplicates.
        top_k = max(Settings.DEFAULT_TOP_K * 6, 30)
        return fused[:top_k]

    def _generate_global_answer_map_reduce(
        self,
        user_id: str,
        query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]],
    ) -> Tuple[str, float, float, float, int, List[str]]:
        """
        Global mode answer generation using map-reduce style synthesis.

        Map phase: summarize evidence from context batches.
        Reduce phase: synthesize all map summaries into final answer.
        """
        map_start = time.time()
        selection_start = time.time()
        selected_communities, selection_ms = self.community_selector.select(
            query=query,
            graph_context=graph_context,
            vector_context=vector_context,
            top_k=3,
        )

        # Merge in persisted communities so global selection is stable across sessions.
        persisted = self.community_persistence.fetch_relevant_communities(
            user_id=user_id,
            query=query,
            top_k=2,
        )
        selected_communities = self._merge_persisted_communities(
            selected_communities,
            persisted,
        )

        community_selection_ms = max(
            selection_ms,
            (time.time() - selection_start) * 1000,
        )

        if not selected_communities:
            return (
                "I don't have enough information in memory to answer that yet.",
                0.0,
                0.0,
                community_selection_ms,
                0,
                [],
            )

        # Map phase over selected communities.
        map_summaries: List[str] = []
        summaries_by_id: Dict[str, str] = {}
        for community in selected_communities:
            map_query = (
                f"Community focus: {community.title}. "
                f"Extract the most important memory points for answering: {query}. "
                f"Consider this community score: {community.score} and return concise evidence bullets."
            )
            map_text = self.answer_generator.generate(
                query=map_query,
                graph_context=community.graph_items,
                vector_context=community.vector_items,
            )
            if map_text:
                map_summaries.append(map_text)
                summaries_by_id[community.id] = map_text

        map_phase_ms = (time.time() - map_start) * 1000

        # Reduce phase to synthesize a final answer.
        reduce_start = time.time()
        reduce_vector_context = [
            {
                "id": f"map_{idx}",
                "text": summary,
                "similarity": 1.0,
                "retrieval_score": 1.0,
                "source_type": "global_map_summary",
            }
            for idx, summary in enumerate(map_summaries, start=1)
        ]

        reduce_query = (
            f"Use the mapped evidence summaries to answer: {query}. "
            "If evidence is weak or missing, clearly say so. "
            "Provide a concise final grounded response."
        )
        final_answer = self.answer_generator.generate(
            query=reduce_query,
            graph_context=graph_context[:4],
            vector_context=reduce_vector_context,
        )
        reduce_phase_ms = (time.time() - reduce_start) * 1000
        selected_ids = [community.id for community in selected_communities]

        refreshed = self.community_persistence.upsert_communities(
            user_id=user_id,
            communities=selected_communities,
            summaries_by_id=summaries_by_id,
        )

        return (
            final_answer,
            map_phase_ms,
            reduce_phase_ms,
            community_selection_ms,
            refreshed,
            selected_ids,
        )

    def _merge_persisted_communities(
        self,
        dynamic_communities: List[CommunityCandidate],
        persisted_records: List[Dict[str, Any]],
    ) -> List[CommunityCandidate]:
        """Blend dynamic communities with persisted ones for stable global routing."""
        merged = list(dynamic_communities)
        seen_ids = {community.id for community in dynamic_communities}

        for record in persisted_records:
            community_id = record.get("id")
            if not community_id or community_id in seen_ids:
                continue

            summary_text = record.get("summary") or ""
            synthetic = CommunityCandidate(
                id=community_id,
                title=record.get("title") or "Community",
                graph_items=[],
                vector_items=[
                    {
                        "id": f"persisted_{community_id}",
                        "text": summary_text,
                        "retrieval_score": max(0.4, float(record.get("persisted_score", 0.0))),
                        "source_type": "persisted_community_summary",
                    }
                ] if summary_text else [],
                score=max(0.3, float(record.get("persisted_score", 0.0))),
                score_breakdown={
                    "semantic": float(record.get("lexical_score", 0.0)),
                    "centrality": float(record.get("persisted_score", 0.0)),
                    "recency": 0.5,
                },
            )
            merged.append(synthetic)
            seen_ids.add(community_id)

        merged.sort(key=lambda community: community.score, reverse=True)
        return merged[:3]

    def _generate_drift_answer(
        self,
        user_id: str,
        query: str,
        retrieval_plan: RetrievalPlan,
        seed_graph_context: List[Dict[str, Any]],
        seed_vector_context: List[Dict[str, Any]],
    ) -> Tuple[str, float, int, int]:
        """
        DRIFT-like iterative retrieval expansion.

        1. Start with seed context from primary retrieval.
        2. Generate follow-up queries from current evidence.
        3. Retrieve additional context for follow-ups.
        4. Synthesize final grounded answer.
        """
        expansion_start = time.time()

        aggregate_graph = list(seed_graph_context)
        aggregate_vector = list(seed_vector_context)

        pending_queries: List[str] = [query]
        visited_queries = {query.strip().lower()}
        total_followups = 0
        iterations = 0

        drift_plan = RetrievalPlan(
            strategy=RetrievalStrategy.LOCAL,
            graph_depth=min(2, retrieval_plan.graph_depth + 1),
            graph_top_k=max(8, retrieval_plan.graph_top_k),
            vector_top_k=max(4, retrieval_plan.vector_top_k),
            enable_vector=retrieval_plan.enable_vector,
        )

        while pending_queries and iterations < self.DRIFT_MAX_DEPTH:
            current_query = pending_queries.pop(0)
            iterations += 1

            graph_context, _ = self._retrieve_graph_sync(user_id, current_query, drift_plan)
            vector_context, _ = self._retrieve_vector_sync(user_id, current_query, drift_plan)

            aggregate_graph = self._merge_unique_graph_nodes(aggregate_graph, graph_context)
            aggregate_vector = self._merge_unique_vector_chunks(aggregate_vector, vector_context)

            followups = self._generate_followup_queries(
                original_query=query,
                active_query=current_query,
                graph_context=aggregate_graph[:10],
                vector_context=aggregate_vector[:6],
            )

            for followup in followups:
                normalized = followup.strip().lower()
                if not normalized or normalized in visited_queries:
                    continue
                visited_queries.add(normalized)
                pending_queries.append(followup)
                total_followups += 1
                if total_followups >= self.DRIFT_MAX_FOLLOWUPS:
                    break

            if total_followups >= self.DRIFT_MAX_FOLLOWUPS:
                break

        final_query = (
            f"Answer this question using the expanded multi-step evidence: {query}. "
            "If memory is incomplete, explicitly mention uncertainty and missing details."
        )
        final_answer = self.answer_generator.generate(
            query=final_query,
            graph_context=aggregate_graph[:12],
            vector_context=aggregate_vector[:8],
        )

        expansion_ms = (time.time() - expansion_start) * 1000
        return final_answer, expansion_ms, iterations, total_followups

    def _generate_followup_queries(
        self,
        original_query: str,
        active_query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate concise follow-up queries for DRIFT expansion."""
        prompt = (
            "Suggest up to 2 short follow-up questions that would improve recall for "
            f"the original user query: {original_query}. Current exploration query: {active_query}. "
            "Return each follow-up on a new line without numbering."
        )
        followup_text = self.answer_generator.generate(
            query=prompt,
            graph_context=graph_context,
            vector_context=vector_context,
        )

        lines = [line.strip(" -•\t") for line in followup_text.splitlines()]
        lines = [line for line in lines if line and len(line) > 8]
        return lines[: self.DRIFT_MAX_FOLLOWUPS]

    def _merge_unique_graph_nodes(
        self,
        base_nodes: List[Dict[str, Any]],
        new_nodes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge graph nodes while deduplicating by node id."""
        merged = list(base_nodes)
        seen_ids = {
            node.get("properties", {}).get("id")
            for node in base_nodes
            if isinstance(node, dict)
        }
        for node in new_nodes:
            node_id = node.get("properties", {}).get("id") if isinstance(node, dict) else None
            if node_id and node_id in seen_ids:
                continue
            merged.append(node)
            if node_id:
                seen_ids.add(node_id)
        return merged

    def _merge_unique_vector_chunks(
        self,
        base_chunks: List[Dict[str, Any]],
        new_chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge vector chunks while deduplicating by vector/chunk id or text."""
        merged = list(base_chunks)
        seen_keys = set()
        for chunk in base_chunks:
            chunk_id = chunk.get("id") if isinstance(chunk, dict) else None
            chunk_text = chunk.get("text") if isinstance(chunk, dict) else None
            seen_keys.add(chunk_id or chunk_text)

        for chunk in new_chunks:
            chunk_id = chunk.get("id") if isinstance(chunk, dict) else None
            chunk_text = chunk.get("text") if isinstance(chunk, dict) else None
            dedup_key = chunk_id or chunk_text
            if not dedup_key or dedup_key in seen_keys:
                continue
            merged.append(chunk)
            seen_keys.add(dedup_key)

        return merged

    def _select_context_by_strategy(
        self,
        fused_results: List[Dict[str, Any]],
        retrieval_plan: RetrievalPlan,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Apply strategy-specific budgets to graph and vector context selection."""
        strategy = retrieval_plan.strategy

        if strategy == RetrievalStrategy.BASIC:
            quality_threshold = 0.12
            graph_limit = 20
            vector_limit = 3
        elif strategy == RetrievalStrategy.GLOBAL:
            quality_threshold = 0.10
            graph_limit = 20
            vector_limit = 6
        elif strategy == RetrievalStrategy.DRIFT:
            quality_threshold = 0.11
            graph_limit = 16
            vector_limit = 6
        else:  # LOCAL default
            quality_threshold = 0.11
            graph_limit = 16
            vector_limit = 5

        quality_filtered = [
            item for item in fused_results
            if item.get("rank_score", item.get("fusion_score", 0.0)) >= quality_threshold
        ]

        graph_context = []
        vector_context = []

        for item in quality_filtered:
            if item.get("source") == "graph" and len(graph_context) < graph_limit:
                graph_context.append(item.get("payload", {}))
            elif item.get("source") == "vector" and len(vector_context) < vector_limit:
                vector_context.append(item.get("payload", {}))

        # Safety fallback to avoid empty answers on sparse memory.
        if not graph_context:
            graph_context = [
                item.get("payload", {})
                for item in fused_results[:graph_limit]
                if item.get("source") == "graph"
            ]
        if not vector_context and retrieval_plan.enable_vector:
            vector_context = [
                item.get("payload", {})
                for item in fused_results[:vector_limit]
                if item.get("source") == "vector"
            ]

        return graph_context, vector_context

    def _avg_confidence(self, context: List[Dict[str, Any]]) -> float:
        """Calculate average confidence score for context items."""
        if not context:
            return 0.5

        confidence_scores = []
        for item in context:
            # Try different confidence field names
            conf = (
                item.get("confidence") or
                item.get("properties", {}).get("confidence") or
                item.get("similarity") or
                item.get("retrieval_score") or
                0.5
            )
            confidence_scores.append(float(conf))

        return sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.5

    def _format_memory_citations(self, fused_results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Format memory citations with retrieval scores for explainability.

        Optimization: Include better confidence indicators and source attribution
        for improved grounding in final answers.

        Returns:
            List of formatted memory citations with snippets and hop distance
        """
        citations = []

        for item in fused_results:
            if item.get("source") == "graph":
                node = item.get("payload", {})
                node_type = node.get("type", "Unknown")
                props = node.get("properties", {})
                score = item.get(
                    "rank_score",
                    node.get("retrieval_score", item.get("fusion_score", 0.0))
                )
                snippet = node.get("snippet", "")
                hop_distance = node.get("score_breakdown", {}).get(
                    "hop_distance", "N/A")

                # Get confidence from node or properties
                confidence = node.get(
                    "confidence", props.get("confidence", 0.7))

                citation = {
                    "node_type": node_type,
                    "retrieval_score": round(score, 4),
                    "confidence": round(confidence, 3),
                    "hop_distance": hop_distance,
                    "snippet": snippet,
                    "source": "graph",
                    "source_weight": item.get("source_weight", 0.5),
                    "properties": {},
                    "score_breakdown": {
                        **(node.get("score_breakdown", {}) or {}),
                        "rank_score": item.get("rank_score", 0.0),
                        "rank_breakdown": item.get("rank_breakdown", {}),
                        "rrf_score": item.get("fusion_score", 0.0),
                        "fusion_weight": item.get("source_weight", 0.5),
                        "source": "graph",
                        "rank": item.get("rank"),
                        "confidence": round(confidence, 3)
                    }
                }

                if node_type == "Fact":
                    citation["properties"] = {
                        "text": props.get("text", ""),
                        "confidence": props.get("confidence", 0.0),
                        "reinforcement_count": props.get("reinforcement_count", 0)
                    }
                elif node_type == "Transaction":
                    citation["properties"] = {
                        "amount": props.get("amount", 0),
                        "transaction_type": props.get("transaction_type", ""),
                        "confidence": props.get("confidence", 0.0)
                    }
                elif node_type in ["Asset", "Goal", "Entity"]:
                    citation["properties"] = {
                        key: value for key, value in props.items()
                        if key in ["name", "text", "confidence", "id"]
                    }

                citations.append(citation)
                continue

            chunk = item.get("payload", {})
            similarity = item.get(
                "rank_score",
                chunk.get("retrieval_score", chunk.get("similarity", 0.0))
            )

            citations.append(
                {
                    "node_type": "DocumentChunk",
                    "retrieval_score": round(similarity, 4),
                    # Use similarity as confidence for vector
                    "confidence": round(similarity, 3),
                    "hop_distance": "vector",
                    # Increased snippet size
                    "snippet": chunk.get("text", "")[:200],
                    "source": "vector",
                    "source_weight": item.get("source_weight", 0.5),
                    "properties": {
                        "chunk_id": chunk.get("id"),
                        "similarity": round(similarity, 4),
                        "source_type": chunk.get("source_type", "vector")
                    },
                    "score_breakdown": {
                        "rank_score": item.get("rank_score", 0.0),
                        "rank_breakdown": item.get("rank_breakdown", {}),
                        "vector_similarity": round(similarity, 4),
                        "rrf_score": item.get("fusion_score", 0.0),
                        "fusion_weight": item.get("source_weight", 0.5),
                        "source": "vector",
                        "rank": item.get("rank")
                    }
                }
            )

        # Sort by composite score: retrieval_score + fusion contribution
        citations.sort(
            key=lambda item: (item.get("retrieval_score", 0.0) * 0.6) +
                             (item.get("source_weight", 0.5) * 0.4),
            reverse=True
        )

        filtered = self._filter_citations_by_query(citations, query)
        return filtered[:12]  # Return up to 12 citations

    def _filter_citations_by_query(self, citations: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Keep only query-relevant citations; fallback to top-ranked if filter is too strict."""
        if not citations:
            return citations

        tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
        stop = {
            "what", "how", "much", "is", "are", "the", "a", "an", "i", "my", "me", "to", "of",
            "in", "on", "for", "and", "or", "have", "has", "had", "do", "did", "does", "all",
        }
        keywords = {token for token in tokens if token not in stop and len(token) > 2}
        if not keywords:
            return citations

        # Topic nudges for financial goal queries.
        goal_query = any(token in keywords for token in {"goal", "retirement", "target", "save", "savings"})

        # "Enumerate / list" queries (e.g. "What stocks do I own?", "List my assets")
        # ask for every entity in a category. The category word (stocks/assets/funds)
        # will NOT appear inside each entity's name, so strict keyword filtering would
        # wrongly drop most of them. For these queries we keep the full ranked set and
        # rely on entity-level dedup downstream.
        LIST_INTENT = {"list", "show", "all", "what", "which", "own", "have", "hold", "holdings"}
        is_list_query = bool(keywords & LIST_INTENT) and any(
            token in keywords for token in {"stocks", "assets", "investments", "funds", "holdings", "portfolio", "transactions"}
        )

        relevant: List[Dict[str, Any]] = []
        for citation in citations:
            node_type = (citation.get("node_type") or "").lower()
            snippet = (citation.get("snippet") or "").lower()
            props = citation.get("properties") or {}
            prop_text = " ".join(str(value).lower() for value in props.values() if isinstance(value, (str, int, float)))
            haystack = f"{snippet} {prop_text}".strip()

            lexical_match = any(keyword in haystack for keyword in keywords)
            type_match = goal_query and node_type in {"goal", "fact", "documentchunk"}

            if is_list_query or lexical_match or type_match:
                relevant.append(citation)

        # If filtering is too strict, keep a small ranked fallback set.
        if len(relevant) < 3:
            return citations[:6]

        # Entity-level deduplication: a single real-world entity (e.g. "Tata Motors")
        # often surfaces as BOTH an Asset node AND a "User holds X shares..." Fact.
        # Keeping both wastes citation slots and pushes distinct entities past the
        # top-k cutoff. Prefer the richer node (Asset/Transaction) and drop the
        # sibling Fact that merely restates the same entity.
        relevant = self._deduplicate_citations_by_entity(relevant)
        return relevant

    def _deduplicate_citations_by_entity(self, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse citations that describe the same entity into a single entry.

        A Fact such as "User holds 20 shares of HDFC Bank..." is a restatement of the
        HDFC Bank Asset node. When both are present we keep the entity node (Asset/
        Transaction/Goal) and drop the redundant Fact, so distinct entities are not
        crowded out of the top-k window.
        """
        # Node types that act as the canonical representation of an entity.
        ENTITY_TYPES = {"asset", "transaction", "goal", "entity"}

        def entity_key(citation: Dict[str, Any]) -> Optional[str]:
            props = citation.get("properties") or {}
            name = props.get("name")
            if name:
                return str(name).strip().lower()
            # Facts carry no name; fall back to their snippet text (normalised).
            snippet = (citation.get("snippet") or "").strip().lower()
            return snippet or None

        kept: List[Dict[str, Any]] = []
        # Track which canonical entity names we've already represented.
        represented_entities: set = set()
        # First pass: keep all entity nodes (Asset/Transaction/Goal) and record names.
        for citation in citations:
            node_type = (citation.get("node_type") or "").lower()
            if node_type in ENTITY_TYPES:
                kept.append(citation)
                key = entity_key(citation)
                if key:
                    represented_entities.add(key)

        # Second pass: keep Facts only if they don't restate an already-represented
        # entity. A Fact restates an entity when its text contains that entity name.
        for citation in citations:
            node_type = (citation.get("node_type") or "").lower()
            if node_type in ENTITY_TYPES:
                continue  # already handled
            snippet = (citation.get("snippet") or "").lower()
            prop_text = " ".join(
                str(v).lower() for v in (citation.get("properties") or {}).values()
                if isinstance(v, (str, int, float))
            )
            haystack = f"{snippet} {prop_text}"
            # Skip this Fact if it mentions an entity we already have a node for.
            if any(name and name in haystack for name in represented_entities):
                continue
            kept.append(citation)

        return kept


    def _parse_strategy_override(self, strategy_override: Optional[str]) -> Optional[RetrievalStrategy]:
        """Parse client-provided mode override into internal retrieval strategy."""
        if not strategy_override:
            return None

        value = strategy_override.strip().lower()
        if value == "auto":
            return None

        mapping = {
            "basic": RetrievalStrategy.BASIC,
            "local": RetrievalStrategy.LOCAL,
            "global": RetrievalStrategy.GLOBAL,
            "drift": RetrievalStrategy.DRIFT,
        }
        return mapping.get(value)

    def close(self):
        """Close all service connections and cleanup resources."""
        self.graph_retrieval.close()
        self.vector_retrieval.close()
        self.community_persistence.close()
        self.hybrid_ranker.close()
        self.executor.shutdown(wait=True)
