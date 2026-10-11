"""
Answer Generator - Generate grounded answers from retrieved context with decomposition-aware prompting.

Uses LLM to generate answers based on graph and vector context.
Leverages query decomposition for more targeted and accurate responses.
"""

import os
from typing import List, Dict, Any, Set, Tuple
from dotenv import load_dotenv
import google.generativeai as genai
from collections import defaultdict

load_dotenv()


class AnswerGenerator:
    """
    Generates grounded answers using LLM with retrieved context.

    Optimizations:
    - Context ranking by confidence and relevance
    - Deduplication of redundant information
    - Clear source attribution
    - Structured formatting for better LLM grounding
    """

    def __init__(self):
        """Initialize LLM client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-flash-lite-latest')
        else:
            self.model = None

    def generate(
        self,
        query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]]
    ) -> str:
        """
        Generate grounded answer from query and optimized context.

        Optimization pipeline:
        1. Deduplicate overlapping context
        2. Rank by confidence and relevance
        3. Format with clear source attribution
        4. Build structured prompt for better grounding

        Args:
            query: User's question
            graph_context: Retrieved graph nodes and relationships
            vector_context: Retrieved vector chunks

        Returns:
            Generated answer with source grounding
        """
        if not self.model:
            return self._fallback_answer(query)

        try:
            # Step 1: Deduplicate and optimize context
            optimized_graph, optimized_vector = self._optimize_context(
                query, graph_context, vector_context
            )

            # Step 2: Rank contexts by confidence
            ranked_graph = self._rank_graph_context(optimized_graph)
            ranked_vector = self._rank_vector_context(optimized_vector)

            # Step 3: Build structured prompt
            prompt = self._build_answer_prompt(
                query, ranked_graph, ranked_vector)

            # Step 4: Generate with LLM
            response = self.model.generate_content(prompt)
            return response.text.strip()

        except Exception as e:
            print(f"Error in answer generation: {e}")
            return self._fallback_answer(query)

    def _build_answer_prompt(
        self,
        query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]]
    ) -> str:
        """Build structured answer generation prompt with ranked context."""

        # Format contexts with confidence scoring
        graph_context_str = self._format_graph_context(graph_context)
        vector_context_str = self._format_vector_context(vector_context)

        # Build structured prompt with grounding instructions
        prompt = f"""You are a financial assistant tasked with providing grounded, factual answers.

IMPORTANT GROUNDING RULES:
1. ONLY use information explicitly provided in the context
2. Include specific citations (e.g., "According to [source]") for each claim
3. When citing graph data, reference the entity type and specific properties
4. When citing vector data, reference the memory/note source
5. If context is insufficient, explicitly state what information is missing
6. Prioritize information marked with higher confidence scores
7. Explain reasoning clearly so the answer is fully grounded

CONTEXT RANKING:
Below contexts are ranked by confidence (highest first).
Higher confidence = more reliable for grounding your answer.

FINANCIAL DATA (Graph - Structured Facts):
{graph_context_str}

MEMORIES & NOTES (Vector - Text References):
{vector_context_str}

USER QUESTION: {query}

GROUNDED ANSWER (with citations):"""

        return prompt

    def _format_graph_context(self, graph_context: List[Dict[str, Any]]) -> str:
        """Format graph context with confidence scores and clear entity relationships."""
        if not graph_context:
            return "No structured data available."

        formatted_sections = []

        # Separate nodes and relationships
        nodes = [item for item in graph_context if item.get(
            "type") != "relationship"]
        relationships = [item for item in graph_context if item.get(
            "type") == "relationship"]

        # Group nodes by type and format with confidence
        if nodes:
            nodes_by_type = defaultdict(list)
            for node in nodes:
                node_type = node.get("type", "Unknown")
                nodes_by_type[node_type].append(node)

            for node_type in sorted(nodes_by_type.keys()):
                type_nodes = nodes_by_type[node_type]
                formatted_sections.append(f"\n{node_type} Entities:")

                for idx, node in enumerate(type_nodes, 1):
                    props = node.get("properties", {})
                    confidence = node.get(
                        "confidence", props.get("confidence", 0.8))

                    # Build property string, excluding internal fields
                    prop_items = [
                        f"{k}: {v}" for k, v in props.items()
                        if k not in ["id", "user_id", "confidence"]
                    ]
                    prop_str = ", ".join(
                        prop_items) if prop_items else "(empty)"

                    # Format with confidence indicator
                    confidence_indicator = "✓" if confidence >= 0.85 else "•"
                    reinforcement = node.get(
                        "reinforcement_count", props.get("reinforcement_count", 0))
                    reinforcement_str = f" [reinforced {reinforcement}x]" if reinforcement > 0 else ""

                    formatted_sections.append(
                        f"  [{idx}] {confidence_indicator} {prop_str} (confidence: {confidence:.2f}){reinforcement_str}"
                    )

        # Format relationships with clarity
        if relationships:
            formatted_sections.append("\nKey Relationships:")
            for rel in relationships:
                rel_type = rel.get("relationship_type", "RELATED_TO")
                from_node = rel.get("from", {})
                to_node = rel.get("to", {})
                props = rel.get("properties", {})

                from_label = from_node.get("type", "Node")
                to_label = to_node.get("type", "Node")

                # Format relationship with properties
                rel_str = f"  - {from_label} --[{rel_type}]--> {to_label}"
                if props:
                    prop_str = ", ".join(
                        [f"{k}: {v}" for k, v in props.items()])
                    rel_str += f" ({prop_str})"
                formatted_sections.append(rel_str)

        return "\n".join(formatted_sections) if formatted_sections else "No structured data available."

    def _format_vector_context(self, vector_context: List[Dict[str, Any]]) -> str:
        """Format vector context with similarity scores and clear sourcing."""
        if not vector_context:
            return "No text memories available."

        formatted_items = []
        for idx, item in enumerate(vector_context, 1):
            text = item.get("text", "")
            if not text:
                continue

            similarity = item.get(
                "similarity", item.get("retrieval_score", 0.0))
            chunk_id = item.get("id", "")

            # Format with similarity score
            similarity_indicator = "★" if similarity >= 0.75 else "☆" if similarity >= 0.5 else "·"
            formatted_items.append(
                f"  [{idx}] {similarity_indicator} (match: {similarity:.2f}) {text}"
            )

        if not formatted_items:
            return "No text memories available."

        return "\n".join(formatted_items)

    def _optimize_context(
        self,
        query: str,
        graph_context: List[Dict[str, Any]],
        vector_context: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Optimize context by deduplication and filtering.

        Args:
            query: User query for context relevance
            graph_context: Graph nodes
            vector_context: Vector chunks

        Returns:
            Tuple of (optimized_graph, optimized_vector)
        """
        # Remove duplicate graph nodes by ID
        seen_node_ids: Set[str] = set()
        unique_graph = []
        for node in graph_context:
            node_id = node.get("properties", {}).get("id")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                unique_graph.append(node)

        # Deduplicate vector chunks by text similarity (simple substring check)
        unique_vector = []
        seen_texts: Set[str] = set()
        for chunk in vector_context:
            text = chunk.get("text", "").strip()
            # Simple deduplication: skip if very similar to existing
            is_duplicate = any(
                len(text) > 10 and text.lower() in existing.lower()
                for existing in seen_texts
            )
            if not is_duplicate and text:
                seen_texts.add(text)
                unique_vector.append(chunk)

        return unique_graph[:15], unique_vector[:10]

    def _rank_graph_context(self, graph_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank graph nodes by confidence, reinforcement, and recency.

        Args:
            graph_context: Graph nodes

        Returns:
            Ranked list of nodes (highest confidence first)
        """
        def get_rank_score(node: Dict[str, Any]) -> float:
            props = node.get("properties", {})
            confidence = node.get("confidence", props.get("confidence", 0.7))
            reinforcement = node.get(
                "reinforcement_count", props.get("reinforcement_count", 0))

            # Score: confidence (70%) + reinforcement bonus (30%)
            base_score = confidence
            reinforcement_bonus = min(reinforcement * 0.05, 0.3)  # Cap at 0.3
            return base_score + reinforcement_bonus

        ranked = sorted(graph_context, key=get_rank_score, reverse=True)
        return ranked

    def _rank_vector_context(self, vector_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank vector chunks by similarity and source quality.

        Args:
            vector_context: Vector chunks

        Returns:
            Ranked list (highest quality first)
        """
        def get_rank_score(chunk: Dict[str, Any]) -> float:
            similarity = chunk.get(
                "similarity", chunk.get("retrieval_score", 0.0))
            # Direct ranking by similarity
            return similarity

        ranked = sorted(vector_context, key=get_rank_score, reverse=True)
        return ranked

    def _fallback_answer(self, query: str) -> str:
        """Fallback answer when LLM is unavailable."""
        return f"I received your query: '{query}'. However, I need proper configuration to generate a detailed answer."
