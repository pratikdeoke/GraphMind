"""
Application settings and configuration.

Loads environment variables and provides configuration constants.
"""

import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()


class Settings:
    """Application settings."""

    # API Settings
    API_TITLE: str = "GraphMind API"
    API_DESCRIPTION: str = "Financial Graph Memory RAG System"
    API_VERSION: str = "1.0.0"
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # LLM Settings
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")

    # Neo4j Settings
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

    # PostgreSQL Settings
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "graphmind")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "graphmind_user")
    POSTGRES_PASSWORD: str = os.getenv(
        "POSTGRES_PASSWORD", "graphmind_pass_2026")

    # Vector Settings
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: str = os.getenv("MILVUS_PORT", "19530")
    MILVUS_COLLECTION: str = os.getenv("MILVUS_COLLECTION", "financial_memory")

    # Embedding Settings
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL", "models/text-embedding-004")
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))

    # Hybrid Retrieval Settings
    VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "8"))
    VECTOR_CANDIDATE_LIMIT: int = int(
        os.getenv("VECTOR_CANDIDATE_LIMIT", "200"))
    HYBRID_FUSION_METHOD: str = os.getenv("HYBRID_FUSION_METHOD", "weighted")
    HYBRID_GRAPH_WEIGHT: float = float(os.getenv("HYBRID_GRAPH_WEIGHT", "0.6"))
    HYBRID_VECTOR_WEIGHT: float = float(
        os.getenv("HYBRID_VECTOR_WEIGHT", "0.4"))

    # Retrieval Settings
    DEFAULT_TOP_K: int = int(os.getenv("DEFAULT_TOP_K", "5"))
    MAX_GRAPH_DEPTH: int = int(os.getenv("MAX_GRAPH_DEPTH", "3"))

    MEMORY_DECAY_ENABLED: bool = os.getenv("MEMORY_DECAY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    MEMORY_DECAY_HALF_LIFE_DAYS: float = float(os.getenv("MEMORY_DECAY_HALF_LIFE_DAYS", "30"))
    MEMORY_DECAY_FLOOR: float = float(os.getenv("MEMORY_DECAY_FLOOR", "0.2"))
    MEMORY_HARD_DECAY_ENABLED: bool = os.getenv("MEMORY_HARD_DECAY_ENABLED", "false").lower() in ("1", "true", "yes", "on")
    MEMORY_HARD_DECAY_INTERVAL_SECONDS: int = int(os.getenv("MEMORY_HARD_DECAY_INTERVAL_SECONDS", "3600"))
    MEMORY_HARD_DECAY_BATCH_SIZE: int = int(os.getenv("MEMORY_HARD_DECAY_BATCH_SIZE", "200"))

    # Community Refresh Settings
    COMMUNITY_REFRESH_ENABLED: bool = os.getenv("COMMUNITY_REFRESH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    COMMUNITY_REFRESH_INTERVAL_SECONDS: int = int(os.getenv("COMMUNITY_REFRESH_INTERVAL_SECONDS", "1800"))
    COMMUNITY_REFRESH_MAX_USERS_PER_CYCLE: int = int(os.getenv("COMMUNITY_REFRESH_MAX_USERS_PER_CYCLE", "50"))
    COMMUNITY_REFRESH_MAX_NODES_PER_USER: int = int(os.getenv("COMMUNITY_REFRESH_MAX_NODES_PER_USER", "300"))
    COMMUNITY_REFRESH_MAX_EDGES_PER_USER: int = int(os.getenv("COMMUNITY_REFRESH_MAX_EDGES_PER_USER", "1000"))
    
    # CORS Settings
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")

    @classmethod
    def validate(cls) -> bool:
        """
        Validate that required settings are present.

        Returns:
            True if all required settings are configured
        """
        required = []

        # Add warnings for missing optional configs
        if not cls.GEMINI_API_KEY:
            print(
                "WARNING: GEMINI_API_KEY not configured. Some features will use fallbacks.")

        return len(required) == 0


# Create global settings instance
settings = Settings()
