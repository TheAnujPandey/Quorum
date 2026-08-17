# Quorum — Architecture Guide

> Complete technical reference for the Quorum agentic RAG platform.
> Covers system design, data flow, every component, and architecture rules.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [High-Level Architecture](#high-level-architecture)
3. [Data Flow — End to End](#data-flow--end-to-end)
4. [API Layer](#api-layer)
5. [Backend / ML Layer](#backend--ml-layer)
6. [Worker Layer](#worker-layer)
7. [Frontend](#frontend)
8. [Database Schema](#database-schema)
9. [Infrastructure & Docker](#infrastructure--docker)
10. [Security Model](#security-model)
11. [Testing](#testing)
12. [Architecture Rules](#architecture-rules)
13. [Known Limitations](#known-limitations)

---

## System Overview

Quorum is an **agentic RAG (Retrieval-Augmented Generation)** platform that
answers natural-language questions over uploaded CSV, Excel, PDF, and TXT
files. It combines local ML models for embedding/reranking with an LLM for
answer generation, orchestrated through a LangGraph corrective agent loop.

**Three application layers:**

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| **API** | `api/` | HTTP coordination: validation, job enqueue, status, `/ask` endpoint |
| **Backend** | `backend/` | Pure ML logic: ingestion, chunking, embeddings, reranking, LangGraph agent |
| **Worker** | `worker/` | Background jobs: chunk, embed, evaluate, cleanup |

**Four persistence stores:**

| Store | Role | Durability |
|-------|------|------------|
| **PostgreSQL** (or SQLite) | Jobs, sessions, chunks, eval results | Durable |
| **Redis** (or in-memory) | Job progress, session cache | Transient, bounded TTL |
| **Qdrant** | Vector embeddings + payload metadata | Durable |
| **MinIO / Local FS** | Raw uploaded files | Durable |

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js 15)                        │
│  Upload Wizard │ Chunk Config │ Preview │ Q&A Panel │ Eval Dashboard│
└────────────┬────────────────────────────────────────────────────────┘
             │ HTTP (port 3000 → 8000)
┌────────────▼────────────────────────────────────────────────────────┐
│                         API (FastAPI)                                │
│  /uploads/*  │  /sessions/*  │  /ask  │  /eval/*  │  /health        │
│                                                                     │
│  Lifespan: DB pool → migrations → bucket → Redis → Qdrant          │
│            → model warmup → optional inline worker                  │
└──┬──────────────┬──────────────┬──────────────┬─────────────────────┘
   │              │              │              │
   ▼              ▼              ▼              ▼
┌──────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│MinIO │   │PostgreSQL│   │  Redis   │   │  Qdrant  │
│(Blob)│   │  (DB)    │   │ (Cache)  │   │(Vectors) │
└──────┘   └────┬─────┘   └──────────┘   └────┬─────┘
                │                              │
         ┌──────▼──────────────────────────────▼─────┐
         │              Worker Process                │
         │  chunk_tabular │ chunk_pdf │ chunk_txt      │
         │  embed_chunks  │ eval_benchmark │ cleanup   │
         │                                             │
         │  Local Models:                              │
         │  • BGE-small-en-v1.5 (384-dim embeddings)   │
         │  • BGE-reranker-base (cross-encoder)        │
         └─────────────────────────────────────────────┘
```

---

## Data Flow — End to End

### Upload → Chunk → Embed → Ask → Answer

```
User selects file
      │
      ▼
POST /uploads/init ─── Creates session row (status: uploading)
      │                 Creates blob staging in MinIO/local
      ▼
PUT /uploads/{id}/chunk/{n} ─── Multipart upload (5 MB parts)
      │
      ▼
POST /uploads/{id}/complete ─── Finalizes blob, detects format
      │                         Session status → uploaded
      ▼
POST /sessions/{id}/chunk ─── User picks method (sentence/fixed/semantic/...)
      │                       Enqueues chunk_tabular / chunk_pdf / chunk_txt
      ▼
Worker: chunk handler
      │  Downloads blob → parses file → applies chunking strategy
      │  Writes draft_chunks to DB → session status → chunked
      ▼
GET /sessions/{id}/chunks ─── Preview: stats + sample chunks
      │
      ▼
POST /sessions/{id}/embed ─── Seeds labeled_qa for eval
      │                       Enqueues embed_chunks job
      ▼
Worker: embed handler
      │  Reads draft_chunks → embeds with BGE → upserts to Qdrant
      │  Session status → ingested
      ▼
POST /ask ─── Runs LangGraph corrective RAG agent:
      │
      │   ┌─────────────────────────────────────────────────────┐
      │   │              LangGraph Agent Flow                    │
      │   │                                                     │
      │   │  retrieve (top-20 from Qdrant)                      │
      │   │      ▼                                              │
      │   │  rerank (cross-encoder → top-3)                     │
      │   │      ▼                                              │
      │   │  grade_documents (LLM: sufficient?)                 │
      │   │      │                                              │
      │   │      ├─ YES → generate (LLM answer with citations)  │
      │   │      │            ▼                                 │
      │   │      │        self_check (faithfulness/relevancy)    │
      │   │      │            ▼                                 │
      │   │      │          DONE → answer + citations + scores   │
      │   │      │                                              │
      │   │      ├─ NO & retries < 2 → rewrite_query → retrieve │
      │   │      │                                              │
      │   │      └─ NO & retries ≥ 2 → respond_insufficient     │
      │   └─────────────────────────────────────────────────────┘
      │
      ▼
Response: { answer, citations[], confidence{} }
```

### Format-Specific Chunking

| Format | Job Type | Default Method | Available Methods | Source Ref |
|--------|----------|---------------|-------------------|------------|
| CSV | `chunk_tabular` | `sentence` | sentence, fixed, recursive | `row:{id}` |
| XLSX | `chunk_tabular` | `sentence` | sentence, fixed, recursive | `row:{id}` |
| PDF | `chunk_pdf` | `semantic` | semantic, fixed, recursive, page | `page:N` |
| TXT | `chunk_txt` | `semantic` | semantic, fixed, recursive, line, paragraph | `chunk:N` |

---

## API Layer

**Entry point:** `api/main.py`

### Endpoints

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| `GET` | `/health` | `health.py` | Readiness check (Postgres, Redis, blob, Qdrant) |
| `GET` | `/config` | `config.py` | Frontend config: default model, key status |
| `POST` | `/uploads/init` | `uploads.py` | Create session + start multipart upload |
| `PUT` | `/uploads/{id}/chunk/{n}` | `uploads.py` | Upload one 5 MB part |
| `POST` | `/uploads/{id}/complete` | `uploads.py` | Finalize upload, detect format |
| `GET` | `/sessions/{id}` | `sessions.py` | Session metadata + chunking config |
| `POST` | `/sessions/{id}/chunk` | `sessions.py` | Enqueue chunking job |
| `GET` | `/sessions/{id}/chunks` | `sessions.py` | Preview draft chunks (stats + sample) |
| `POST` | `/sessions/{id}/embed` | `sessions.py` | Seed eval data, enqueue embedding job |
| `DELETE` | `/sessions/{id}` | `sessions.py` | Full cleanup: Qdrant + blob + DB + cache |
| `GET` | `/jobs/{id}` | `jobs.py` | Job status with progress from Redis |
| `POST` | `/ask` | `ask.py` | Synchronous RAG agent call |
| `POST` | `/eval/run` | `eval.py` | Enqueue benchmark evaluation |
| `GET` | `/eval/runs` | `eval.py` | List recent eval runs |
| `GET` | `/eval/runs/{id}` | `eval.py` | Eval run detail with per-question results |

### Core Modules

| Module | File | Role |
|--------|------|------|
| **config** | `api/core/config.py` | Pydantic settings from `.env` |
| **db** | `api/core/db.py` | Dual-backend: asyncpg (Postgres) or aiosqlite; migrations |
| **jobs** | `api/core/jobs.py` | `enqueue_job()` + optional immediate dispatch |
| **redis_client** | `api/core/redis_client.py` | Redis with automatic in-memory fallback |
| **memory_cache** | `api/core/memory_cache.py` | In-process TTL cache when Redis is unavailable |
| **cache** | `api/core/cache.py` | TTL constants: job=1h, session=7d, upload=24h |
| **blob_store** | `api/core/blob_store.py` | Facade: S3/MinIO (aioboto3) or local filesystem |
| **qdrant_client** | `api/core/qdrant_client.py` | Async Qdrant; 384-dim cosine vectors |
| **logging** | `api/core/logging.py` | structlog JSON logger |
| **seed** | `api/core/seed.py` | Seeds `labeled_qa` from `db/seed/labeled_qa.json` |

### Startup Sequence

```
DB pool → run migrations → ensure blob bucket → connect Redis
→ ensure Qdrant collection → warmup embedding + reranker models
→ (optional) start inline worker poll loop
```

---

## Backend / ML Layer

### LangGraph Agent (`backend/agent/`)

**State schema** (`graph.py` — `AgentState`):

| Field | Type | Purpose |
|-------|------|---------|
| `session_id` | str | Scopes Qdrant queries |
| `question` | str | Original user question |
| `rewritten_question` | str | Refined query after failed retrieval |
| `chunks` | list[dict] | Retrieved + reranked context |
| `retries_used` | int | Rewrite loop counter (max 2) |
| `sufficient` | bool | Grade result |
| `answer` | str | Generated answer |
| `insufficient` | bool | True when max retries exceeded |
| `confidence` | dict | `{faithfulness, answer_relevancy, label}` |
| `citations` | list[dict] | Top-3 source excerpts with refs |

**Graph topology:**

```
START → retrieve → rerank → grade_documents
                              ├─ sufficient → generate → self_check → END
                              ├─ retries < 2 → rewrite_query → retrieve (loop)
                              └─ retries ≥ 2 → respond_insufficient → END
```

**Concurrency:** Semaphore on LLM calls (default limit: 10).

**Per-request LLM overrides:** `llm_context.py` uses a `ContextVar` so each
`/ask` request can supply its own API key/model without affecting other requests.

### Node Implementations (`backend/agent/nodes.py`)

| Node | What it does |
|------|-------------|
| `retrieve_chunks` | Embeds question → Qdrant top-20 search filtered by `session_id` |
| `rerank_chunks` | BGE cross-encoder scores query-chunk pairs → keeps top 3 |
| `grade_documents` | LLM judges if chunks can answer the question → JSON `{sufficient, reasoning}` |
| `rewrite_query` | LLM rewrites question for better retrieval |
| `generate_answer` | LLM generates answer strictly from chunks with `[source_ref]` citations |
| `self_check` | LLM scores `faithfulness` and `answer_relevancy` (0–1), assigns confidence label |

### Prompt Templates (`backend/agent/prompts.py`)

All prompts use `ChatPromptTemplate.from_messages()` with system/human pairs:

| Template | Output Format | Purpose |
|----------|--------------|---------|
| `GRADE_DOCUMENTS` | JSON `{sufficient, reasoning}` | Judge retrieval quality |
| `REWRITE_QUERY` | JSON `{rewritten_query, strategy}` | Improve search query |
| `GENERATE_ANSWER` | Plain text with `[source_ref]` | Answer from documents only |
| `SELF_CHECK` | JSON `{faithfulness, answer_relevancy, label, citations}` | Score and extract citations |
| `INSUFFICIENT_RESPONSE` | Plain text | Fixed fallback message |

### Embedding Model (`backend/embeddings/model.py`)

- **Model:** BAAI/bge-small-en-v1.5
- **Library:** sentence-transformers `SentenceTransformer`
- **Dimensions:** 384 (L2-normalized)
- **Loading:** Lazy singleton with async lock + thread pool
- **Version tracking:** Stored in every Qdrant point payload

### Reranker Model (`backend/reranker/model.py`)

- **Model:** BAAI/bge-reranker-base
- **Library:** sentence-transformers `CrossEncoder`
- **Input:** (query, passage) pairs
- **Output:** Score-sorted indices
- **Loading:** Lazy singleton with async lock

### Ingestion Pipeline (`backend/ingestion/`)

| Module | Purpose |
|--------|---------|
| `detect_format.py` | Maps file extension → `csv`, `xlsx`, `pdf`, `txt` |
| `tabular_split.py` | Classifies columns (narrative/categorical/ID), builds row narratives |
| `chunker.py` | Semantic chunking (LangChain `SemanticChunker`) + fallback splitting |
| `chunk_strategies.py` | Dispatcher for sentence/fixed/recursive/semantic/line/paragraph methods |
| `pdf_parser.py` | pypdf text + pdfplumber tables per page → structured output |

**Key design decisions:**
- Tables are never split mid-row (preserves data integrity)
- Categorical columns become Qdrant payload metadata, not embedded text
- Null bytes stripped from PDF content (prevents Postgres UTF-8 errors)
- Long text fallback: paragraph → sentence splitting at 2000 char max

---

## Worker Layer

**Entry point:** `worker/main.py`

### Job Types

| Job Type | Handler | Trigger | Output |
|----------|---------|---------|--------|
| `chunk_tabular` | `chunk_tabular.py` | `POST /sessions/{id}/chunk` (CSV/XLSX) | `draft_chunks` rows |
| `chunk_pdf` | `chunk_pdf.py` | `POST /sessions/{id}/chunk` (PDF) | `draft_chunks` rows |
| `chunk_txt` | `chunk_txt.py` | `POST /sessions/{id}/chunk` (TXT) | `draft_chunks` rows |
| `embed_chunks` | `embed_chunks.py` | `POST /sessions/{id}/embed` | Qdrant vectors |
| `eval_benchmark` | `eval_benchmark.py` | `POST /eval/run` | `eval_runs` + `eval_results` |
| `ingest_tabular` | `ingest_tabular.py` | Legacy one-shot | — |
| `cleanup` | `cleanup.py` | Auto every 15 min | Deletes expired sessions |

### Job Queue

- **Postgres:** `FOR UPDATE SKIP LOCKED` — safe for multiple worker replicas
- **SQLite:** Simple SELECT + UPDATE (single worker only)
- **Progress:** Cached in Redis with `cache_job_status()` for real-time polling
- **Stale recovery:** `fail_stale_jobs()` marks orphaned running jobs as failed on worker start
- **Inflight guard:** `_INFLIGHT` set prevents duplicate dispatch

### Session Status Progression

```
uploading → uploaded → chunking → chunked → embedding → ingested
                                                          │
                                              DELETE /sessions/{id}
                                              or TTL expiry → cleaned
```

### Cleanup Job

Runs every 15 minutes. For each session where `expires_at < now()`:
1. Delete Qdrant vectors (filtered by `session_id`)
2. Delete blob from S3/MinIO (best-effort)
3. Delete `draft_chunks`, `labeled_qa`, `sessions` rows

---

## Frontend

**Framework:** Next.js 15 (App Router), React 18, Tailwind CSS, TanStack React Query

### Pages

| Route | File | Purpose |
|-------|------|---------|
| `/` | `app/page.tsx` | Main wizard: upload → chunk → preview → embed → Q&A |
| `/eval` | `app/eval/page.tsx` | Eval dashboard: run benchmarks, view results |
| `/settings` | `app/settings/page.tsx` | API URL, OpenAI key/model config |

### Components

| Component | Purpose |
|-----------|---------|
| `ChunkMethodForm` | Format-aware chunking method selector + config fields |
| `ChunkPreview` | Chunk statistics + sample display |
| `PipelineProgress` | Stage stepper with progress bar |
| `QnaPanel` | Question input, answer history, citations, confidence badges |
| `ThemeToggle` | Light/dark mode toggle |

### State Management

| Data | Strategy | Storage |
|------|----------|---------|
| Server data (sessions, jobs) | TanStack React Query with polling | In-memory |
| Session/job IDs | `useState` + `localStorage` | `localStorage` |
| OpenAI API key | `sessionStorage` (clears on tab close) | `sessionStorage` |
| App settings (URL, model) | `localStorage` | `localStorage` |
| Chunking preferences | `localStorage` | `localStorage` |
| Theme | React Context + `localStorage` | `localStorage` |
| Q&A history | Component state | Ephemeral |

### API Client (`lib/api-client.ts`)

Wraps all API calls with automatic base URL resolution, error handling, and
multipart upload orchestration (5 MB slices with progress callback).

---

## Database Schema

### Entity Relationship

```
sessions 1──* draft_chunks     (session_id FK)
sessions 1──* labeled_qa       (session_id FK)
eval_runs 1──* eval_results    (eval_run_id FK)
labeled_qa 1──* eval_results   (labeled_qa_id FK)
jobs                           (standalone queue)
```

### Tables

**`jobs`** — Durable async job queue

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | |
| `job_type` | TEXT | chunk_tabular, embed_chunks, etc. |
| `status` | TEXT | pending / running / completed / failed |
| `payload` | JSONB | Job parameters |
| `result_ref` | TEXT | JSON result on completion |
| `error` | TEXT | Failure message |
| `claimed_by` | TEXT | Worker ID |
| `attempts` | INT | Retry count |
| Index: `(status, created_at)` | | Job claiming performance |

**`sessions`** — Upload + pipeline state

| Column | Type | Purpose |
|--------|------|---------|
| `session_id` | UUID PK | |
| `source_format` | TEXT | csv / xlsx / pdf / txt |
| `blob_key` | TEXT | S3 or local path to raw file |
| `qdrant_collection` | TEXT | Default: `quorum_chunks` |
| `upload_status` | TEXT | Pipeline status |
| `chunk_count` | INT | Number of chunks produced |
| `chunking_method` | TEXT | Method used |
| `chunking_config` | JSONB | Method parameters |
| `expires_at` | TIMESTAMPTZ | TTL for auto-cleanup (7 days) |

**`draft_chunks`** — Intermediate chunks before/after embedding

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Also used as Qdrant point ID |
| `session_id` | UUID FK | Links to session |
| `chunk_index` | INT | Ordering |
| `source_ref` | TEXT | `row:X`, `page:N`, `chunk:N` |
| `chunk_text` | TEXT | Content |
| `char_count` | INT | Length tracking |
| `categorical_metadata` | JSONB | Tabular column metadata (Qdrant payload) |
| Index: `(session_id, chunk_index)` | | Ordered retrieval |

**`labeled_qa`** — Evaluation question-answer pairs

| Column | Type | Purpose |
|--------|------|---------|
| `id` | SERIAL PK | |
| `session_id` | UUID FK | Nullable |
| `question` | TEXT | |
| `expected_answer` | TEXT | |
| `expected_source_ref` | TEXT | For retrieval hit checking |

**`eval_runs`** — Evaluation run summaries

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | |
| `run_type` | TEXT | `benchmark` or `live_sample` |
| `avg_retrieval_hit_rate` | FLOAT | |
| `avg_answer_correctness` | FLOAT | |
| `avg_faithfulness` | FLOAT | |
| `avg_answer_relevancy` | FLOAT | |
| `question_count` | INT | |

**`eval_results`** — Per-question evaluation results

| Column | Type | Purpose |
|--------|------|---------|
| `eval_run_id` | UUID FK | Links to eval_runs |
| `labeled_qa_id` | INT FK | Links to labeled_qa |
| `generated_answer` | TEXT | |
| `retrieved_source_refs` | TEXT[] | |
| `retrieval_hit` | BOOLEAN | |
| `faithfulness` | FLOAT | 0–1 score |
| `answer_relevancy` | FLOAT | 0–1 score |
| `retries_used` | INT | |

---

## Infrastructure & Docker

### Docker Compose Services

| Service | Image | Ports | Role |
|---------|-------|-------|------|
| **postgres** | `postgres:16-alpine` | — | Primary database |
| **redis** | `redis:7-alpine` | 6379 | Cache + job progress |
| **minio** | MinIO | 9000, 9001 | S3-compatible blob store |
| **minio-init** | `minio/mc` | — | Creates upload bucket |
| **qdrant** | `qdrant/qdrant:v1.13.2` | 6333 | Vector database |
| **api** | `Dockerfile.api` | 8000 | FastAPI application |
| **worker** | `Dockerfile.worker` | — | Background job processor |
| **frontend** | `frontend/Dockerfile` | 3000 | Next.js application |

### Build Strategy

```
Dockerfile.base (Python 3.11 slim + CPU torch + all Python deps)
    ├── Dockerfile.api    (extends base → uvicorn)
    └── Dockerfile.worker (extends base → python -m worker.main)

frontend/Dockerfile (Node 20 multi-stage → standalone Next.js)
```

Shared base image avoids rebuilding ML dependencies for each service.

### Volumes

| Volume | Stores |
|--------|--------|
| `postgres_data` | Database files |
| `minio_data` | Uploaded raw files |
| `qdrant_data` | Vector indices |
| `model_cache` | HuggingFace model weights (shared by api + worker) |

### Makefile Targets

| Target | Action |
|--------|--------|
| `make base` | Build `quorum-base` image |
| `make up` | Build all + start stack |
| `make down` | Stop stack |
| `make restart` | Full rebuild + restart |
| `make logs` | Follow api/worker/frontend logs |
| `make clean` | Stop + remove all volumes |
| `make test` | Run pytest |
| `make lint` | Run ruff linter |

---

## Security Model

### API Key Handling

- **Frontend:** Stored in `sessionStorage` — automatically cleared when the
  browser tab or window is closed. Never persisted to `localStorage` or cookies.
- **Backend:** Per-request override via request body. Held only in a
  request-scoped `ContextVar`, never written to DB or Redis.
- **Server fallback:** Optional `OPENAI_API_KEY` in `.env` (never committed).
- **Clear Session:** Explicitly wipes `sessionStorage` API key + all server data.

### Data Lifecycle

- Sessions auto-expire after 7 days (configurable `session_ttl_days`)
- Manual "Clear Session" performs full cleanup: DB rows + Qdrant vectors + blob files + Redis cache
- TTL cleanup job runs every 15 minutes as a secondary safeguard

### Prompt Injection Defense

- All file/chunk content is treated as **data, never instructions** (Rule R11)
- No arbitrary code execution tool in the agent (Rule R12)
- Retrieved content placed in structured prompt slots, never concatenated as system instructions

---

## Testing

| Test File | Coverage |
|-----------|----------|
| `tests/backend/test_agent_nodes.py` | Agent node functions: grade, rewrite, generate, self_check (mocked LLM) |
| `tests/backend/test_chunk_strategies.py` | All chunking methods: sentence, fixed, recursive, semantic, line, paragraph |
| `tests/backend/test_chunker.py` | Text splitting boundaries, semantic chunker fallback |
| `tests/backend/test_detect_format.py` | File extension → format mapping |
| `tests/backend/test_pdf_parser.py` | Table-to-markdown conversion, empty PDF handling |
| `tests/backend/test_tabular_split.py` | Column classification heuristics, narrative/payload building |
| `tests/conftest.py` | Shared fixtures: sample CSV/TXT bytes, mock 384-dim embeddings |

**Run:** `make test` or `uv run pytest tests -v`

---

## Architecture Rules

These rules are mandatory for all code in this repository.

### R0 — Async I/O Only
All I/O (database, cache, blob, Qdrant, HTTP) is asynchronous. No blocking
calls inside async handlers.

### R1 — API Layer Does Not Ingest
Route handlers validate, enqueue, and report. All parsing, chunking, embedding,
and Qdrant writes happen in `worker/job_handlers/`. Exception: `/ask` is
synchronous because it operates on already-embedded, small top-3 context.

### R2 — Ingestion Is Always a Job
Any file parse, chunking pass, or embedding computation goes through
`enqueue_job()`. Never process a full document inline in a request handler.

### R3 — Job Claiming Uses SKIP LOCKED
```sql
SELECT * FROM jobs WHERE status = 'pending'
ORDER BY created_at LIMIT $1 FOR UPDATE SKIP LOCKED
```
Safe for multiple worker replicas.

### R4 — No Module-Level Mutable State
Exception: embedding and reranker model singletons (expensive weights, loaded
once per process). LangGraph state is request-scoped and discarded after.

### R5 — Bounded TTLs in Redis
Every key has an explicit TTL. Constants in `api/core/cache.py`.

### R6 — Chunking Never Splits Tables Mid-Row
Tables from PDFs or CSV/Excel rows are chunked as whole units.

### R7 — Narrative and Categorical Fields Separated
CSV/Excel: narrative fields → embedded chunk text. Categorical fields → Qdrant
payload metadata for filtering.

### R8 — Embedding Model Consistency
Same model at ingestion and query time. Version tracked in Qdrant payload.
Model upgrade = full re-embedding.

### R9 — /ask Is Synchronous but Bounded
Hard retry cap (2 retries, 3 total), request timeout, LLM concurrency
semaphore.

### R10 — Agent Can Say "I Don't Know"
`respond_insufficient` is a required, reachable path. Never run `generate` on
context flagged as insufficient.

### R11 — File Content Is Data, Not Instructions
Retrieved/uploaded content never concatenated as prompt instructions.

### R12 — No Arbitrary Code Execution
The agent answers through retrieval + LLM generation only. No code-exec tools.

### R13 — Benchmark Before Changing Retrieval
Any chunking/embedding/reranker/retrieval change must be validated with
`POST /eval/run` before and after.

### R14 — Secrets Never Enter the Image
No `.env`, API key, or credential committed or `COPY`'d into Docker images.

### R15 — One Entry Point Per Service
`api/main.py` for the API. `worker/main.py` for the worker. No duplicates.

### R16 — Observability on Every Job and Agent Run
Structured logging for session, job type, timestamps, success/failure, retries,
confidence scores. Never bare `print()`.

---

## Known Limitations

- **No authentication layer** — disclosed, not hidden; add before production
- **Scanned/image-only PDFs unsupported** — fails clearly; OCR is a future extension
- **Purely numeric spreadsheets** get limited RAG value — accepted tradeoff
- **Self-check scores are informational** — drive the confidence badge, don't trigger retries
- **Eval set starts small** (10–20 questions) — useful but not statistically rigorous
- **Single Qdrant collection** — all sessions share one collection, filtered by `session_id`
