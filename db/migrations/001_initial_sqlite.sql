CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payload TEXT NOT NULL,
    result_ref TEXT,
    error TEXT,
    claimed_by TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL,
    blob_key TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    chunk_count INTEGER,
    upload_status TEXT NOT NULL DEFAULT 'initiated',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labeled_qa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(session_id),
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    avg_retrieval_hit_rate REAL,
    avg_answer_correctness REAL,
    avg_faithfulness REAL,
    avg_answer_relevancy REAL,
    question_count INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id TEXT REFERENCES eval_runs(id),
    labeled_qa_id INTEGER REFERENCES labeled_qa(id),
    generated_answer TEXT,
    retrieved_source_refs TEXT,
    retrieval_hit INTEGER,
    answer_correctness REAL,
    faithfulness REAL,
    answer_relevancy REAL,
    retries_used INTEGER
);
