from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from enum import Enum


class IntentType(str, Enum):
    """Intent classification for chat requests"""
    MEMORY = "MEMORY"
    QUESTION = "QUESTION"
    BOTH = "BOTH"


class RetrievalModeSelector(str, Enum):
    """Optional override for retrieval strategy routing."""

    AUTO = "auto"
    BASIC = "basic"
    LOCAL = "local"
    GLOBAL = "global"
    DRIFT = "drift"


class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    user_id: str = Field(
        ...,
        description="User UUID from the frontend context. This field is accepted for compatibility.",
        example="f4a2fca4-39d0-4028-8fb5-4f0b84b6c9d5"
    )
    message: str = Field(
        ...,
        min_length=1,
        description="User message to ingest as memory and/or answer as a question.",
        example="How much have I invested this month?"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Optional conversation identifier reserved for future multi-thread support.",
        example=None
    )
    retrieval_mode: RetrievalModeSelector = Field(
        default=RetrievalModeSelector.AUTO,
        description="Optional retrieval strategy override: auto, basic, local, global, or drift.",
        example="auto"
    )


class RetrievalMetrics(BaseModel):
    """Detailed metrics for retrieval and generation performance"""
    graph_query_ms: float = Field(
        ..., description="Time spent on graph retrieval in milliseconds.", example=34.2)
    vector_search_ms: float = Field(
        ..., description="Time spent on vector retrieval in milliseconds.", example=0.0)
    context_assembly_ms: float = Field(
        ..., description="Time to assemble context in milliseconds.", example=5.4)
    retrieval_ms: float = Field(
        ..., description="Total retrieval time in milliseconds.", example=45.1)
    llm_generation_ms: float = Field(
        ..., description="LLM answer generation time in milliseconds.", example=502.7)


class MemoryCitation(BaseModel):
    """Memory citation with retrieval score for explainability"""
    node_type: str = Field(...,
                           description="Type of cited graph node.", example="Fact")
    retrieval_score: float = Field(
        ..., description="Final ranking score for the citation.", example=0.91)
    hop_distance: Any = Field(
        ..., description="Shortest path hop distance from user context.", example=1)
    snippet: str = Field(..., description="Human-readable citation snippet.",
                         example="Investment in HDFC Mutual Fund")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Raw node properties used for explainability.")
    score_breakdown: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional weighted score components: graph_distance, recency, confidence, reinforcement."
    )
    source: str = Field(
        default="hybrid", description="Source of the citation: 'graph', 'vector', or 'hybrid'.", example="graph")


class MemoryStorageResult(BaseModel):
    """Result of memory storage operation"""
    nodes_created: int = Field(...,
                               description="Number of graph nodes created.", example=4)
    relationships_created: int = Field(
        ..., description="Number of graph relationships created.", example=3)
    facts_created: int = Field(...,
                               description="Number of normalized facts extracted.", example=2)
    chunks_indexed: int = Field(
        ..., description="Number of chunks indexed for retrieval.", example=1)


class AnswerEvaluation(BaseModel):
    """Heuristic quality evaluation for generated answers."""
    overall_score: float = Field(
        ..., description="Overall answer quality score in [0,1].", example=0.81)
    quality_label: str = Field(...,
                               description="Discrete quality bucket.", example="good")
    groundedness_score: float = Field(
        ..., description="How well claims are grounded in citations.", example=0.84)
    citation_quality_score: float = Field(
        ..., description="Citation strength based on count, score, and diversity.", example=0.79)
    relevance_score: float = Field(
        ..., description="Query-answer topical overlap score.", example=0.76)
    completeness_score: float = Field(
        ..., description="Estimated completeness for the asked question.", example=0.8)
    hallucination_risk: float = Field(
        ..., description="Estimated hallucination risk in [0,1].", example=0.18)
    supported_claim_ratio: float = Field(
        ..., description="Ratio of detected claims supported by evidence.", example=0.83)
    unsupported_claim_ratio: float = Field(
        ..., description="Ratio of detected claims lacking evidence.", example=0.17)
    citation_count: int = Field(...,
                                description="Total citations used for evaluation.", example=4)
    graph_citation_count: int = Field(...,
                                      description="Graph citations count.", example=3)
    vector_citation_count: int = Field(...,
                                       description="Vector citations count.", example=1)
    avg_citation_score: float = Field(
        ..., description="Average retrieval score across citations.", example=0.74)
    numeric_claim_support_ratio: float = Field(
        ..., description="Support ratio for numeric claims.", example=1.0)
    latency_penalty: float = Field(
        ..., description="Small penalty applied for very high latency.", example=0.01)
    summary: str = Field(..., description="Human-readable quality summary.")


class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    intent: IntentType
    answer: Optional[str] = None
    memory_storage: Optional[MemoryStorageResult] = None
    retrieval_metrics: Optional[RetrievalMetrics] = None
    memory_citations: Optional[List[MemoryCitation]] = None
    answer_evaluation: Optional[AnswerEvaluation] = None
    message: str


# ── Document Upload Models ──────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """Response from document upload and extraction"""
    success: bool
    filename: str
    format: str
    extraction_method: str
    text_preview: str
    extracted_text: str  # Full extracted text from document
    metadata: dict
    message: str
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None


class DocumentIngestionRequest(BaseModel):
    """Request to ingest extracted document text into graph"""
    user_id: str
    document_text: str
    document_name: str
    document_format: str
    metadata: Optional[dict] = None


class DocumentIngestionResponse(BaseModel):
    """Response from document ingestion into graph"""
    success: bool
    document_name: str
    extracted_text: str
    extraction_stats: dict
    llm_extraction: Optional[dict] = None
    memory_storage: Optional[MemoryStorageResult] = None
    message: str
