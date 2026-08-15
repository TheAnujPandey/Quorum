-- Draft chunks for preview-before-embed wizard
CREATE TABLE IF NOT EXISTS draft_chunks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    chunk_index INTEGER NOT NULL,
    source_ref TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    categorical_metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_draft_chunks_session ON draft_chunks (session_id, chunk_index);

-- Session chunking metadata (SQLite: ADD COLUMN is idempotent via try/except in runner)
-- Applied via migration runner with IF NOT EXISTS pattern for columns
