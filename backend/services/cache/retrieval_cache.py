"""
Retrieval result caching for sub-100ms optimization.

Caches:
- Graph retrieval results (5-minute TTL)
- Vector search results (5-minute TTL)
- Query embeddings (24-hour TTL)
"""

from typing import Dict, Any, List, Optional, Tuple
import time
import hashlib
from collections import OrderedDict


class RetrievalCache:
    """
    In-memory LRU cache for retrieval results.

    Optimizations:
    - Caches graph + vector results to avoid redundant queries
    - TTL-based expiration
    - LRU eviction policy (max 1000 entries)
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of cache entries (LRU eviction)
            ttl_seconds: Time-to-live for cached entries (default: 5 minutes)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def get(self, user_id: str, query: str, cache_type: str = "retrieval") -> Optional[Dict[str, Any]]:
        """
        Get cached result if available and not expired.

        Args:
            user_id: User identifier
            query: Query text
            cache_type: Type of cache (retrieval, embedding, etc.)

        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(user_id, query, cache_type)

        if key not in self.cache:
            return None

        entry = self.cache[key]

        # Check expiration
        if time.time() > entry["expires_at"]:
            del self.cache[key]
            return None

        # Update LRU order (move to end)
        self.cache.move_to_end(key)

        return entry["data"]

    def set(self, user_id: str, query: str, data: Dict[str, Any], cache_type: str = "retrieval") -> None:
        """
        Cache a result.

        Args:
            user_id: User identifier
            query: Query text
            data: Data to cache
            cache_type: Type of cache
        """
        key = self._make_key(user_id, query, cache_type)

        # Evict oldest entry if cache is full
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)  # Remove oldest (first) entry

        self.cache[key] = {
            "data": data,
            "expires_at": time.time() + self.ttl_seconds,
            "created_at": time.time()
        }

        # Move to end (most recently used)
        self.cache.move_to_end(key)

    def invalidate_user(self, user_id: str) -> int:
        """
        Invalidate all cache entries for a user (e.g., after ingestion).

        Args:
            user_id: User identifier

        Returns:
            Number of entries invalidated
        """
        keys_to_delete = [
            k for k in self.cache.keys() if k.startswith(f"{user_id}:")]
        for key in keys_to_delete:
            del self.cache[key]
        return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds
        }

    @staticmethod
    def _make_key(user_id: str, query: str, cache_type: str = "retrieval") -> str:
        """
        Generate cache key from user_id and query.

        Args:
            user_id: User identifier
            query: Query text
            cache_type: Type of cache

        Returns:
            Cache key
        """
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        return f"{user_id}:{cache_type}:{query_hash}"


# Global cache instance
_retrieval_cache: Optional[RetrievalCache] = None


def get_retrieval_cache() -> RetrievalCache:
    """Get or create global retrieval cache."""
    global _retrieval_cache
    if _retrieval_cache is None:
        _retrieval_cache = RetrievalCache(max_size=1000, ttl_seconds=300)
    return _retrieval_cache
