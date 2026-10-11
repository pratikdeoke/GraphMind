"""Embedding service with Gemini-first and deterministic local fallback."""

from __future__ import annotations

from typing import List
import hashlib
import importlib
import math
import os

from config.settings import Settings


class EmbeddingService:
    """Generates text embeddings for vector retrieval."""

    def __init__(self):
        self.dimension = Settings.EMBEDDING_DIMENSION
        self.model_name = Settings.EMBEDDING_MODEL
        self._gemini_enabled = False
        self._genai = None

        api_key = Settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai = importlib.import_module("google.generativeai")
                genai.configure(api_key=api_key)
                self._genai = genai
                self._gemini_enabled = True
            except Exception:
                self._gemini_enabled = False

    def embed_text(self, text: str) -> List[float]:
        """Return embedding vector for a single text."""
        cleaned = (text or "").strip()
        if not cleaned:
            return [0.0] * self.dimension

        if self._gemini_enabled and self._genai is not None:
            try:
                result = self._genai.embed_content(
                    model=self.model_name,
                    content=cleaned,
                    task_type="RETRIEVAL_DOCUMENT"
                )
                raw = result.get("embedding", []) if isinstance(
                    result, dict) else []
                if raw:
                    return self._normalize(self._fit_dimension(raw))
            except Exception:
                pass

        return self._hash_embedding(cleaned)

    def embed_query(self, query: str) -> List[float]:
        """Return embedding vector for query text."""
        cleaned = (query or "").strip()
        if not cleaned:
            return [0.0] * self.dimension

        if self._gemini_enabled and self._genai is not None:
            try:
                result = self._genai.embed_content(
                    model=self.model_name,
                    content=cleaned,
                    task_type="RETRIEVAL_QUERY"
                )
                raw = result.get("embedding", []) if isinstance(
                    result, dict) else []
                if raw:
                    return self._normalize(self._fit_dimension(raw))
            except Exception:
                pass

        return self._hash_embedding(cleaned)

    def _fit_dimension(self, values: List[float]) -> List[float]:
        """Pad or truncate to configured embedding dimension."""
        if len(values) == self.dimension:
            return [float(v) for v in values]
        if len(values) > self.dimension:
            return [float(v) for v in values[: self.dimension]]

        padded = [float(v) for v in values]
        padded.extend([0.0] * (self.dimension - len(values)))
        return padded

    def _hash_embedding(self, text: str) -> List[float]:
        """Deterministic fallback embedding based on token hashing."""
        vector = [0.0] * self.dimension
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vector[bucket] += sign * weight

        return self._normalize(vector)

    @staticmethod
    def _normalize(vector: List[float]) -> List[float]:
        """L2 normalize vector."""
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]
