-- Add answer evaluation metrics storage for assistant messages.
-- Safe to run multiple times on PostgreSQL.

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS answer_eval_metrics JSONB;
