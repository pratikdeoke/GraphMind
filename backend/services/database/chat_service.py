"""
Chat Service - PostgreSQL-based chat history management
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
from database.postgres import PostgresDB


class ChatService:
    """Manage chat sessions and messages in PostgreSQL."""

    @staticmethod
    def create_session(user_id: str, title: str = "New Chat") -> Dict[str, Any]:
        """Create a new chat session."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                INSERT INTO chat_sessions (user_id, title)
                VALUES (%s, %s)
                RETURNING id, user_id, title, created_at, updated_at
            """, (user_id, title))

            session = cur.fetchone()
            return dict(session) if session else None

    @staticmethod
    def get_or_create_session(user_id: str) -> Dict[str, Any]:
        """Get the user's single persistent session or create one if missing."""
        with PostgresDB.get_cursor() as cur:
            # Fetch latest session regardless of archive state
            cur.execute("""
                SELECT id, user_id, title, created_at, updated_at, is_archived
                FROM chat_sessions
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
            """, (user_id,))
            session = cur.fetchone()

            if session:
                session = dict(session)
                # If archived, unarchive to keep a single persistent chat
                if session.get("is_archived"):
                    cur.execute("""
                        UPDATE chat_sessions
                        SET is_archived = FALSE, updated_at = NOW()
                        WHERE id = %s
                    """, (session["id"],))
                    session["is_archived"] = False
                return session

            # No session exists for this user; create one
            return ChatService.create_session(user_id)

    @staticmethod
    def get_user_sessions(user_id: str, include_archived: bool = False, limit: int = 1) -> List[Dict[str, Any]]:
        """Get the user's persistent session (always a single active chat)."""
        with PostgresDB.get_cursor() as cur:
            archived_filter = "" if include_archived else "AND cs.is_archived = FALSE"

            cur.execute(f"""
                SELECT 
                    cs.id, 
                    cs.title, 
                    cs.created_at, 
                    cs.updated_at,
                    cs.is_archived,
                    COUNT(cm.id) as message_count
                FROM chat_sessions cs
                LEFT JOIN chat_messages cm ON cs.id = cm.session_id
                WHERE cs.user_id = %s {archived_filter}
                GROUP BY cs.id
                ORDER BY cs.updated_at DESC
                LIMIT %s
            """, (user_id, limit))

            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def add_message(
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        neo4j_message_id: Optional[str] = None,
        graph_query_ms: Optional[float] = None,
        vector_search_ms: Optional[float] = None,
        retrieval_time_ms: Optional[float] = None,
        llm_generation_time_ms: Optional[float] = None,
        nodes_retrieved: Optional[int] = None,
        memory_storage: Optional[dict] = None,
        memory_citations: Optional[list] = None,
        answer_eval_metrics: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Add a message to a chat session.

        Args:
            session_id: Chat session UUID
            user_id: User UUID
            role: 'user' or 'assistant'
            content: Message text
            intent: Optional intent classification
            neo4j_message_id: Optional Neo4j Message node ID
            graph_query_ms: Optional graph retrieval time
            vector_search_ms: Optional vector retrieval time
            retrieval_time_ms: Optional retrieval time
            llm_generation_time_ms: Optional LLM generation time
            nodes_retrieved: Optional count of retrieved nodes
            memory_storage: Optional JSON metadata
            memory_citations: Optional JSON citations array
            answer_eval_metrics: Optional JSON answer quality evaluation
        """
        import json
        from psycopg2.extras import Json

        print(f"All parameters received in add_message: session_id={session_id}, user_id={user_id}, role={role}, content={content}, intent={intent}, neo4j_message_id={neo4j_message_id}, retrieval_time_ms={retrieval_time_ms}, llm_generation_time_ms={llm_generation_time_ms}, nodes_retrieved={nodes_retrieved}, memory_storage={memory_storage}, memory_citations={memory_citations}, answer_eval_metrics={answer_eval_metrics}")
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                INSERT INTO chat_messages (
                    session_id, user_id, role, content, intent,
                    neo4j_message_id, graph_query_ms, vector_search_ms, retrieval_time_ms, llm_generation_time_ms,
                    nodes_retrieved, memory_storage, memory_citations, answer_eval_metrics
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, session_id, role, content, created_at
            """, (
                session_id,
                user_id,
                role,
                content,
                intent if isinstance(intent, str) else Json(
                    intent) if intent is not None else None,
                neo4j_message_id,
                graph_query_ms,
                vector_search_ms,
                retrieval_time_ms,
                llm_generation_time_ms,
                nodes_retrieved,
                Json(memory_storage) if memory_storage is not None else None,
                Json(memory_citations) if memory_citations is not None else None,
                Json(answer_eval_metrics) if answer_eval_metrics is not None else None
            ))

            message = cur.fetchone()

            cur.execute("""
                UPDATE chat_sessions
                SET updated_at = NOW()
                WHERE id = %s
            """, (session_id,))

            return dict(message) if message else None

    @staticmethod
    def get_session_messages(session_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get all messages in a session."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT 
                    id, session_id, user_id, role, content, intent,
                    created_at, graph_query_ms, vector_search_ms, retrieval_time_ms, llm_generation_time_ms,
                    nodes_retrieved, memory_storage, memory_citations, answer_eval_metrics
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at ASC
                LIMIT %s OFFSET %s
            """, (session_id, limit, offset))

            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_user_recent_messages(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get user's recent messages across all sessions."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT 
                    id, session_id, role, content, intent, created_at,
                    graph_query_ms, vector_search_ms, retrieval_time_ms, llm_generation_time_ms
                FROM chat_messages
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))

            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def update_session_title(session_id: str, title: str):
        """Update session title."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE chat_sessions
                SET title = %s, updated_at = NOW()
                WHERE id = %s
            """, (title, session_id))

    @staticmethod
    def archive_session(session_id: str):
        """Archive a session."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE chat_sessions
                SET is_archived = TRUE, updated_at = NOW()
                WHERE id = %s
            """, (session_id,))

    @staticmethod
    def delete_session(session_id: str):
        """Delete a session and all its messages (CASCADE)."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                DELETE FROM chat_sessions
                WHERE id = %s
            """, (session_id,))
