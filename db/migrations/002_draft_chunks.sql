CREATE TABLE IF NOT EXISTS draft_chunks (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    chunk_index INT NOT NULL,
    source_ref TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    char_count INT NOT NULL,
    categorical_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_draft_chunks_session ON draft_chunks (session_id, chunk_index);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS chunking_method TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS chunking_config JSONB;
