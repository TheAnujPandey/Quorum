CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL,
    result_ref TEXT,
    error TEXT,
    claimed_by TEXT,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_format TEXT NOT NULL,
    blob_key TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    chunk_count INT,
    upload_status TEXT NOT NULL DEFAULT 'initiated',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS labeled_qa (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id),
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type TEXT NOT NULL,
    avg_retrieval_hit_rate FLOAT,
    avg_answer_correctness FLOAT,
    avg_faithfulness FLOAT,
    avg_answer_relevancy FLOAT,
    question_count INT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS eval_results (
    id SERIAL PRIMARY KEY,
    eval_run_id UUID REFERENCES eval_runs(id),
    labeled_qa_id INT REFERENCES labeled_qa(id),
    generated_answer TEXT,
    retrieved_source_refs TEXT[],
    retrieval_hit BOOLEAN,
    answer_correctness FLOAT,
    faithfulness FLOAT,
    answer_relevancy FLOAT,
    retries_used INT
);
