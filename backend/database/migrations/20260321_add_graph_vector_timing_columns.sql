-- Add separate timing columns for graph and vector retrieval metrics.
-- Safe to run multiple times.

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS graph_query_ms FLOAT;

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS vector_search_ms FLOAT;
