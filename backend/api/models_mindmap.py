"""
Memory Mindmap Models - For graph visualization
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any


class MindmapNode(BaseModel):
    """Node in the mindmap graph."""
    id: str = Field(..., description="Unique node id.", example="fact_1")
    type: str = Field(..., description="Graph node label/type.", example="Fact")
    label: str = Field(..., description="Display label for visualization.", example="Invested in HDFC Mutual Fund")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Node metadata key/value pairs.")


class MindmapEdge(BaseModel):
    """Edge/relationship in the mindmap graph."""
    id: str = Field(..., description="Unique relationship id.", example="rel_1")
    source: str = Field(..., description="Source node id.", example="user_1")
    target: str = Field(..., description="Target node id.", example="fact_1")
    type: str = Field(..., description="Relationship type.", example="OWNS_MEMORY")
    label: str = Field(..., description="Display label for visualization.", example="OWNS_MEMORY")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Relationship metadata key/value pairs.")


class MindmapResponse(BaseModel):
    """Response containing nodes and edges for visualization."""
    nodes: List[MindmapNode] = Field(default_factory=list, description="All nodes in the user's graph.")
    edges: List[MindmapEdge] = Field(default_factory=list, description="All edges in the user's graph.")
    total_nodes: int = Field(..., description="Total number of nodes.", example=12)
    total_edges: int = Field(..., description="Total number of edges.", example=21)
