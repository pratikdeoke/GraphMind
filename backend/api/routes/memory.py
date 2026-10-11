"""
Memory/Mindmap Routes - Visualization endpoints
"""

from fastapi import APIRouter, HTTPException, status, Header
from typing import Optional, List
from pydantic import BaseModel
from api.models_mindmap import MindmapResponse, MindmapNode, MindmapEdge
from services.graph.mindmap_service import mindmap_service
from services.graph.community_refresh import CommunityRefreshService
from services.auth.auth_service import auth_service
from services.database.user_service import UserService

router = APIRouter()

# Initialize user service
user_service = UserService()
community_refresh_service = CommunityRefreshService()


class ClearGraphResponse(BaseModel):
    """Response model for graph clearing operation."""
    success: bool
    message: str
    deleted_nodes: int = 0
    deleted_vectors: int = 0


class VectorEntry(BaseModel):
    """Vector database entry model."""
    vector_id: str
    text: str
    source_type: str
    confidence: float
    chunk_index: int
    timestamp: str
    metadata: dict


class VectorDBResponse(BaseModel):
    """Response model for vector database entries."""
    entries: List[VectorEntry]
    total_entries: int


class CommunityRefreshResponse(BaseModel):
    """Response model for community refresh trigger."""

    success: bool
    message: str
    communities_upserted: int = 0
    stale_deleted: int = 0


def get_user_from_token(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract user_id from JWT token.

    Args:
        authorization: Authorization header with Bearer token

    Returns:
        user_id string

    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return payload["user_id"]


@router.get(
    "/mindmap",
    response_model=MindmapResponse,
    summary="Get memory mindmap",
    description="Return all knowledge-graph nodes and edges for the authenticated user.",
    responses={
        200: {"description": "Mindmap data returned successfully."},
        400: {"description": "User is not linked to a knowledge graph."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "User not found."}
    }
)
async def get_mindmap(
    authorization: Optional[str] = Header(
        default=None,
        description="Bearer token. Format: 'Bearer <access_token>'"
    )
):
    """
    Get user's memory graph for visualization.

    Returns all nodes and edges for the authenticated user's
    knowledge graph, formatted for mindmap visualization.

    Args:
        authorization: JWT token in Authorization header

    Returns:
        MindmapResponse with nodes and edges
    """
    # Get PostgreSQL user_id from JWT token
    pg_user_id = get_user_from_token(authorization)

    # Get user's neo4j_user_id from PostgreSQL (for backward compatibility)
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Try neo4j_user_id first, then fall back to pg_user_id for backward compatibility
    neo4j_user_id = user.get("neo4j_user_id")

    # Get graph data using whichever user_id has data
    # First try neo4j_user_id, then fall back to pg_user_id
    nodes_data, edges_data = mindmap_service.get_user_graph(
        neo4j_user_id) if neo4j_user_id else ([], [])

    if not nodes_data and not edges_data:
        # Fall back to pg_user_id for backward compatibility
        nodes_data, edges_data = mindmap_service.get_user_graph(pg_user_id)

    # Convert to Pydantic models
    nodes = [MindmapNode(**node) for node in nodes_data]
    edges = [MindmapEdge(**edge) for edge in edges_data]

    return MindmapResponse(
        nodes=nodes,
        edges=edges,
        total_nodes=len(nodes),
        total_edges=len(edges)
    )


@router.delete(
    "/clear",
    response_model=ClearGraphResponse,
    summary="Clear knowledge graph",
    description="Delete all nodes, edges, and vectors for the authenticated user.",
    responses={
        200: {"description": "Knowledge graph cleared successfully."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "User not found."}
    }
)
async def clear_knowledge_graph(
    authorization: Optional[str] = Header(
        default=None,
        description="Bearer token. Format: 'Bearer <access_token>'"
    )
):
    """
    Clear user's entire knowledge graph and vector database.

    Deletes all:
    - Nodes from Neo4j graph database
    - Relationships from Neo4j graph database
    - Vectors from Milvus vector database

    This operation is irreversible.

    Args:
        authorization: JWT token in Authorization header

    Returns:
        ClearGraphResponse with deletion summary
    """
    # Get PostgreSQL user_id from JWT token
    pg_user_id = get_user_from_token(authorization)

    # Get user's neo4j_user_id from PostgreSQL (for backward compatibility)
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Try neo4j_user_id first, then fall back to pg_user_id for backward compatibility
    neo4j_user_id = user.get("neo4j_user_id")
    user_id_to_delete = neo4j_user_id if neo4j_user_id else pg_user_id

    # Delete from Neo4j
    graph_result = mindmap_service.delete_user_graph(user_id_to_delete)

    # Delete from Milvus
    vector_result = mindmap_service.delete_user_vectors(user_id_to_delete)

    # Combine results
    total_success = graph_result.get(
        "success", False) and vector_result.get("success", False)

    return ClearGraphResponse(
        success=total_success,
        message=(
            f"Graph cleared: {graph_result.get('message', '')} | "
            f"Vectors cleared: {vector_result.get('message', '')}"
        ),
        deleted_nodes=graph_result.get("deleted_nodes", 0),
        deleted_vectors=vector_result.get("deleted_vectors", 0)
    )


@router.get(
    "/vectors",
    response_model=VectorDBResponse,
    summary="Get vector database entries",
    description="Return all vector database entries for the authenticated user.",
    responses={
        200: {"description": "Vector entries retrieved successfully."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "User not found."}
    }
)
async def get_vector_entries(
    authorization: Optional[str] = Header(
        default=None,
        description="Bearer token. Format: 'Bearer <access_token>'"
    ),
    limit: int = 100
):
    """
    Get user's vector database entries for visualization.

    Returns all vector entries stored in Milvus for the authenticated user.

    Args:
        authorization: JWT token in Authorization header
        limit: Maximum number of entries to return (default: 100)

    Returns:
        VectorDBResponse with vector entries
    """
    # Get PostgreSQL user_id from JWT token
    pg_user_id = get_user_from_token(authorization)

    # Get user from database
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Try neo4j_user_id first, then fall back to pg_user_id
    neo4j_user_id = user.get("neo4j_user_id")
    target_user_id = neo4j_user_id if neo4j_user_id else pg_user_id

    # Get vector entries from Milvus
    try:
        vectors = mindmap_service.get_user_vectors(target_user_id, limit=limit)

        # Convert to VectorEntry models
        entries = [
            VectorEntry(
                vector_id=v.get("vector_id", ""),
                text=v.get("text", ""),
                source_type=v.get("source_type", ""),
                confidence=float(v.get("confidence", 0.0)),
                chunk_index=int(v.get("chunk_index", 0)),
                timestamp=v.get("timestamp", ""),
                metadata=v.get("metadata", {})
            )
            for v in vectors
        ]

        return VectorDBResponse(
            entries=entries,
            total_entries=len(entries)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving vector entries: {str(e)}"
        )


@router.post(
    "/communities/refresh",
    response_model=CommunityRefreshResponse,
    summary="Refresh persisted communities",
    description="Recompute and persist stable community clusters for the authenticated user.",
    responses={
        200: {"description": "Community refresh completed successfully."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "User not found."},
    },
)
async def refresh_communities(
    authorization: Optional[str] = Header(
        default=None,
        description="Bearer token. Format: 'Bearer <access_token>'"
    )
):
    """Trigger one-shot community refresh for the authenticated user."""
    pg_user_id = get_user_from_token(authorization)

    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    neo4j_user_id = user.get("neo4j_user_id")
    target_user_id = neo4j_user_id if neo4j_user_id else pg_user_id

    communities_upserted, stale_deleted = community_refresh_service.refresh_user_once(
        str(target_user_id)
    )

    return CommunityRefreshResponse(
        success=True,
        message="Community refresh completed.",
        communities_upserted=communities_upserted,
        stale_deleted=stale_deleted,
    )
