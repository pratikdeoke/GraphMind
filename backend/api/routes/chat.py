from fastapi import APIRouter, HTTPException, Depends, Header, status, Query, Path
from typing import Optional, List
from api.models import ChatRequest, ChatResponse, IntentType, MemoryStorageResult, RetrievalMetrics, AnswerEvaluation, MemoryCitation
from services.llm.intent_classifier import IntentClassifier
from services.orchestrator.memory_orchestrator import MemoryOrchestrator
from services.orchestrator.retrieval_orchestrator import RetrievalOrchestrator
from services.evaluation.answer_quality_evaluator import AnswerQualityEvaluator
from services.database.chat_service import ChatService
from services.database.user_service import UserService
from services.auth.auth_service import auth_service
from pydantic import BaseModel

router = APIRouter()

# Initialize services
intent_classifier = IntentClassifier()
memory_orchestrator = MemoryOrchestrator()
retrieval_orchestrator = RetrievalOrchestrator()
answer_quality_evaluator = AnswerQualityEvaluator()
chat_service = ChatService()
user_service = UserService()


async def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract user ID from JWT token.

    Returns:
        User's PostgreSQL UUID

    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Extract token from "Bearer <token>"
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

    # Verify token
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return payload["user_id"]


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a chat message",
    description=(
        "Unified endpoint that auto-classifies each message into MEMORY, QUESTION, "
        "or BOTH. It persists user/assistant messages and may ingest memory, answer "
        "a question, or do both in one call."
    ),
    responses={
        200: {"description": "Chat processed successfully."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "Authenticated user not found."}
    }
)
async def chat_endpoint(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Unified chat endpoint supporting:
    - Memory ingestion (MEMORY)
    - Question answering (QUESTION)
    - Both operations (BOTH)

    Automatically persists chat messages to PostgreSQL.
    """
    # Get user's neo4j_user_id for graph operations
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    neo4j_user_id = user["neo4j_user_id"]

    # Get or create active session for user
    session = chat_service.get_or_create_session(user_id)
    session_id = session["id"]

    # Store user message
    user_message = chat_service.add_message(
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=request.message,
        intent=None,  # We'll update this after classification
        neo4j_message_id=None
    )

    # Step 1: Classify intent
    intent = intent_classifier.classify(request.message)

    # Update user message with intent classification
    # (Could add a method to update message intent, but skip for now)

    response_data = None
    assistant_content = None
    graph_query_time = None
    vector_search_time = None
    retrieval_time = None
    llm_generation_time = None
    nodes_retrieved = 0
    memory_storage_data = None
    memory_citations_data = None
    answer_eval_data = None

    if intent == "MEMORY":
        # Handle memory ingestion only
        storage_result = memory_orchestrator.ingest_memory(
            user_id=neo4j_user_id,
            message=request.message
        )

        assistant_content = "Financial memory stored successfully."
        memory_storage_data = storage_result

        response_data = ChatResponse(
            intent=IntentType.MEMORY,
            memory_storage=MemoryStorageResult(**storage_result),
            message=assistant_content
        )

    elif intent == "QUESTION":
        # Handle query retrieval and answer generation
        answer, metrics, memory_citations = retrieval_orchestrator.retrieve_and_answer(
            user_id=neo4j_user_id,
            query=request.message,
            strategy_override=request.retrieval_mode.value
        )

        assistant_content = answer
        graph_query_time = metrics.get("graph_query_ms", 0)
        vector_search_time = metrics.get("vector_search_ms", 0)
        retrieval_time = metrics.get("retrieval_ms", 0)
        llm_generation_time = metrics.get("llm_generation_ms", 0)
        nodes_retrieved = len(memory_citations) if memory_citations else 0
        # memory_citations is already a list of dicts from the orchestrator; store as-is
        memory_citations_data = memory_citations if memory_citations else None
        typed_citations = [MemoryCitation(
            **item) for item in memory_citations] if memory_citations else None
        answer_eval_data = answer_quality_evaluator.evaluate(
            query=request.message,
            answer=answer,
            memory_citations=memory_citations,
            retrieval_metrics=metrics,
        )

        response_data = ChatResponse(
            intent=IntentType.QUESTION,
            answer=answer,
            retrieval_metrics=RetrievalMetrics(**metrics),
            memory_citations=typed_citations,
            answer_evaluation=AnswerEvaluation(**answer_eval_data),
            message="Answer generated successfully."
        )

    elif intent == "BOTH":
        # Handle both memory ingestion and query
        storage_result = memory_orchestrator.ingest_memory(
            user_id=neo4j_user_id,
            message=request.message
        )

        answer, metrics, memory_citations = retrieval_orchestrator.retrieve_and_answer(
            user_id=neo4j_user_id,
            query=request.message,
            strategy_override=request.retrieval_mode.value
        )

        assistant_content = answer
        graph_query_time = metrics.get("graph_query_ms", 0)
        vector_search_time = metrics.get("vector_search_ms", 0)
        retrieval_time = metrics.get("retrieval_ms", 0)
        llm_generation_time = metrics.get("llm_generation_ms", 0)
        nodes_retrieved = len(memory_citations) if memory_citations else 0
        memory_storage_data = storage_result
        # memory_citations is already a list of dicts from the orchestrator; store as-is
        memory_citations_data = memory_citations if memory_citations else None
        typed_citations = [MemoryCitation(
            **item) for item in memory_citations] if memory_citations else None
        answer_eval_data = answer_quality_evaluator.evaluate(
            query=request.message,
            answer=answer,
            memory_citations=memory_citations,
            retrieval_metrics=metrics,
        )

        response_data = ChatResponse(
            intent=IntentType.BOTH,
            answer=answer,
            memory_storage=MemoryStorageResult(**storage_result),
            retrieval_metrics=RetrievalMetrics(**metrics),
            memory_citations=typed_citations,
            answer_evaluation=AnswerEvaluation(**answer_eval_data),
            message="Memory stored and answer generated."
        )

    # Store assistant response with metadata
    assistant_message = chat_service.add_message(
        session_id=session_id,
        user_id=user_id,
        role="assistant",
        content=assistant_content or "No response generated.",
        intent=intent,
        neo4j_message_id=None,
        graph_query_ms=graph_query_time,
        vector_search_ms=vector_search_time,
        retrieval_time_ms=retrieval_time,
        llm_generation_time_ms=llm_generation_time,
        nodes_retrieved=nodes_retrieved,
        memory_storage=memory_storage_data,
        memory_citations=memory_citations_data,
        answer_eval_metrics=answer_eval_data
    )

    return response_data


# Response models for history endpoints
class SessionResponse(BaseModel):
    """Session information"""
    id: str
    title: str
    created_at: Optional[str]
    updated_at: Optional[str]
    is_archived: bool = False
    message_count: int = 0


class MessageResponse(BaseModel):
    """Chat message information"""
    id: str
    session_id: str
    role: str
    content: str
    intent: Optional[str]
    created_at: Optional[str]
    graph_query_ms: Optional[float]
    vector_search_ms: Optional[float]
    retrieval_time_ms: Optional[float]
    llm_generation_time_ms: Optional[float]
    nodes_retrieved: Optional[int]
    memory_storage: Optional[dict]
    memory_citations: Optional[list]
    answer_eval_metrics: Optional[dict]


class SessionActionResponse(BaseModel):
    """Simple response model for session actions."""
    message: str


@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    summary="List user sessions",
    description="Return chat sessions for the authenticated user.",
    responses={
        200: {"description": "Sessions fetched successfully."},
        401: {"description": "Missing, invalid, or expired token."}
    }
)
async def get_user_sessions(
    user_id: str = Depends(get_current_user_id),
    include_archived: bool = Query(
        default=False,
        description="Set true to include archived sessions in the result."
    )
):
    """
    Get all chat sessions for the current user.

    Args:
        user_id: Extracted from JWT token
        include_archived: Whether to include archived sessions

    Returns:
        List of chat sessions
    """
    sessions = chat_service.get_user_sessions(user_id, include_archived)

    return [
        SessionResponse(
            id=str(session["id"]),
            title=session["title"],
            created_at=session["created_at"].isoformat(
            ) if session.get("created_at") else None,
            updated_at=session["updated_at"].isoformat(
            ) if session.get("updated_at") else None,
            is_archived=session.get("is_archived", False),
            message_count=session.get("message_count", 0)
        )
        for session in sessions
    ]


@router.get(
    "/sessions/{session_id}/messages",
    response_model=List[MessageResponse],
    summary="Get session messages",
    description="Return paginated messages for a specific session.",
    responses={
        200: {"description": "Messages fetched successfully."},
        401: {"description": "Missing, invalid, or expired token."},
        403: {"description": "Session does not belong to current user."}
    }
)
async def get_session_messages(
    session_id: str = Path(..., description="Session UUID.",
                           example="3a640334-9816-4f3b-8b4f-4dbf03b80229"),
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=50, ge=1, le=500,
                       description="Maximum number of messages to return."),
    offset: int = Query(
        default=0, ge=0, description="Number of messages to skip.")
):
    """
    Get all messages for a specific chat session.

    Args:
        session_id: Session UUID
        user_id: Extracted from JWT token (for authorization)
        limit: Maximum number of messages to return
        offset: Number of messages to skip

    Returns:
        List of chat messages

    Raises:
        HTTPException: If session doesn't belong to user
    """
    messages = chat_service.get_session_messages(session_id, limit, offset)

    # Verify session belongs to user
    if messages and messages[0].get("user_id") != user_id:
        raise HTTPException(
            status_code=403, detail="Access denied to this session")

    return [
        MessageResponse(
            id=str(msg["id"]),
            session_id=str(msg["session_id"]),
            role=msg["role"],
            content=msg["content"],
            intent=msg.get("intent"),
            created_at=msg["created_at"].isoformat(
            ) if msg.get("created_at") else None,
            graph_query_ms=msg.get("graph_query_ms"),
            vector_search_ms=msg.get("vector_search_ms"),
            retrieval_time_ms=msg.get("retrieval_time_ms"),
            llm_generation_time_ms=msg.get("llm_generation_time_ms"),
            nodes_retrieved=msg.get("nodes_retrieved"),
            memory_storage=msg.get("memory_storage"),
            memory_citations=msg.get("memory_citations"),
            answer_eval_metrics=msg.get("answer_eval_metrics")
        )
        for msg in messages
    ]


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionActionResponse,
    summary="Archive session",
    description="Archive a chat session for the authenticated user.",
    responses={
        200: {"description": "Session archived."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "Session not found."}
    }
)
async def archive_session(
    session_id: str = Path(..., description="Session UUID.",
                           example="3a640334-9816-4f3b-8b4f-4dbf03b80229"),
    user_id: str = Depends(get_current_user_id)
):
    """Archive a chat session."""
    success = chat_service.archive_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"message": "Session archived successfully"}


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionActionResponse,
    summary="Delete session",
    description="Delete a chat session and all associated messages.",
    responses={
        200: {"description": "Session deleted."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "Session not found."}
    }
)
async def delete_session(
    session_id: str = Path(..., description="Session UUID.",
                           example="3a640334-9816-4f3b-8b4f-4dbf03b80229"),
    user_id: str = Depends(get_current_user_id)
):
    """Delete a chat session and all its messages."""
    success = chat_service.delete_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"message": "Session deleted successfully"}
