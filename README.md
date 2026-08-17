# Quorum

An agentic RAG platform that answers questions over CSV, Excel, PDF, and TXT uploads. Built with a LangGraph corrective RAG agent, local embeddings, cross-encoder reranking, and a dual-track evaluation system.

## How It Works

Upload a document. Quorum splits it into chunks — narrative text is semantically chunked, tabular data is split into narrative vs. categorical fields (categorical metadata becomes Qdrant payload filters instead of being embedded). Ask a question and the LangGraph agent:

1. **Retrieves** top-20 candidates from Qdrant (with optional payload filtering)
2. **Reranks** via a cross-encoder to the top 3
3. **Grades** whether the context is sufficient (LLM judge)
4. **Rewrites** the query and retries up to 2 more times if insufficient
5. **Generates** a cited answer or honestly says "I don't know"
6. **Self-checks** faithfulness and relevancy, surfaced as a confidence badge

```
Upload → Format Detection → Chunk → Preview → Embed → Qdrant
                                                          ↓
Question → Retrieve → Rerank → Grade ──→ Generate → Self-check → Answer
                        ↑         │
                        └─ Rewrite ┘ (up to 2 retries)
```

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15, React 19, TanStack Query, Tailwind |
| API | FastAPI (async) |
| Agent | LangGraph StateGraph (corrective RAG with conditional retry) |
| Embeddings | `bge-small-en-v1.5` via sentence-transformers (local, no per-call cost) |
| Reranker | `bge-reranker-base` cross-encoder (local) |
| Chunking | Semantic (LangChain `SemanticChunker`), sentence, fixed, recursive |
| Vector DB | Qdrant |
| LLM | OpenAI `gpt-4o-mini` |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Blob Storage | MinIO (S3-compatible) |
| Job Queue | Postgres + `SELECT ... FOR UPDATE SKIP LOCKED` |
| CI/CD | GitHub Actions (lint → test → build → smoke-test) |

## Supported Formats

| Format | Parsing | Chunking |
|---|---|---|
| CSV | Polars, narrative/categorical column split | Sentence, fixed, recursive, or semantic |
| Excel (.xlsx) | Polars `read_excel`, same column split | Sentence, fixed, recursive, or semantic |
| PDF | pypdf (text) + pdfplumber (tables as markdown) | Semantic (tables kept as whole chunks) |
| TXT | UTF-8 / Latin-1 auto-detect | Semantic |

## Quick Start

### Prerequisites

| Requirement | macOS | Windows |
|---|---|---|
| Docker Desktop | [Download for Mac](https://www.docker.com/products/docker-desktop/) | [Download for Windows](https://www.docker.com/products/docker-desktop/) -- enable **WSL2 backend** (Settings > General > "Use the WSL 2 based engine") |
| Git | Pre-installed or `brew install git` | [Download Git for Windows](https://git-scm.com/download/win) |
| OpenAI API key | Can be added later via the frontend Settings page | Same |

### macOS / Linux Setup

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd quorum

# 2. Create your environment file
cp .env.example .env
# (Optional) Open .env and add your OPENAI_API_KEY -- or paste it in the frontend later

# 3. Build and start everything (one command)
make up
```

Three commands and the project is running.

### Windows Setup (PowerShell or CMD)

```powershell
# 1. Clone and enter the project
git clone <repo-url>
cd quorum

# 2. Create your environment file
copy .env.example .env
# (Optional) Open .env and add your OPENAI_API_KEY -- or paste it in the frontend later

# 3. Build the base Python image
docker build -t quorum-base -f Dockerfile.base .

# 4. Start all services
docker compose up -d --build
```

> **Tip:** Windows does not ship with `make`. To use the shorter `make` commands, install it via [Chocolatey](https://chocolatey.org/) (`choco install make`) or [Scoop](https://scoop.sh/) (`scoop install make`). After that, all `make` commands work identically to macOS.

### After Startup

Once all containers are running, these services are available:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| MinIO console | http://localhost:9001 |
| Qdrant dashboard | http://localhost:6333/dashboard |

### First-Time Usage

1. Open **Settings** at http://localhost:3000/settings -- paste your OpenAI API key
2. Upload a CSV, Excel, PDF, or TXT file on the home page
3. Choose a chunking method appropriate for your file format
4. Preview chunks, then click **Embed chunks & index**
5. Ask questions in the Q&A panel

### Commands

| What you want to do | macOS / Linux (`make`) | Windows (direct) |
|---|---|---|
| Start all services | `make up` | `docker build -t quorum-base -f Dockerfile.base . && docker compose up -d --build` |
| Stop all services | `make down` | `docker compose down` |
| Rebuild and restart | `make restart` | `docker compose down && docker build -t quorum-base -f Dockerfile.base . && docker compose up -d --build` |
| View logs | `make logs` | `docker compose logs -f api worker frontend` |
| Stop and delete all data | `make clean` | `docker compose down -v` |
| Run tests | `make test` | `uv run pytest tests -v` |
| Run linter | `make lint` | `uv run ruff check api backend worker` |
| Seed eval Q&A | `make seed` | `docker compose exec api python scripts/seed_labeled_qa.py --file db/seed/labeled_qa.json` |
| Check health | `curl http://localhost:8000/health` | `curl http://localhost:8000/health` (or open in browser) |

## Project Structure

```
api/                    FastAPI gateway (thin — validation, auth, job enqueue)
├── routes/             uploads, sessions, ask, eval, jobs, health
├── core/               db, redis, blob_store, qdrant_client, config
└── models/             Pydantic schemas

backend/                Pure logic — no FastAPI imports
├── agent/              LangGraph graph, node functions, prompts
├── ingestion/          Format detection, PDF parser, chunker, tabular split
├── embeddings/         Shared embedding model singleton
└── reranker/           Shared cross-encoder singleton

worker/                 Background job processor
├── scheduler.py        SKIP LOCKED job claiming + dispatch
└── job_handlers/       chunk_tabular, chunk_pdf, chunk_txt, embed_chunks,
                        eval_benchmark, cleanup

frontend/               Next.js app
├── app/                Pages: home (upload wizard), eval dashboard, settings
├── components/         ChunkMethodForm, ChunkPreview, QnaPanel, PipelineProgress
└── lib/                API client, settings, chunking config

tests/                  pytest suite (58 tests)
├── backend/            Chunker, tabular split, PDF parser, agent nodes, format detection
└── core/               Integration test fixtures

db/migrations/          Postgres + SQLite migration scripts
.github/workflows/      CI/CD pipeline
```

## Evaluation System

Quorum has a dual-track evaluation system:

**Benchmark (on-demand):** Runs the full agent against a labeled Q&A set and computes retrieval hit rate, answer correctness, faithfulness, and answer relevancy. View results on the eval dashboard at `/eval`.

**Continuous (live sampling):** 20% of live `/ask` calls are sampled — self-check scores are logged to `eval_results` as `live_sample` runs, visible alongside benchmark runs on the dashboard.

## Domain Coverage: RAG, ML, MLOps & Agentic AI

This project covers four key domains end-to-end. Here is exactly where each one plays a role:

### RAG (Retrieval-Augmented Generation)

The core architecture of the entire platform — from document ingestion to grounded answer generation.

| Stage | What happens | Files |
|---|---|---|
| **Ingestion** | Documents are parsed, split into chunks (sentence/fixed/recursive/semantic), and narrative vs. categorical fields are separated for tabular data | `backend/ingestion/chunker.py`, `chunk_strategies.py`, `tabular_split.py`, `pdf_parser.py` |
| **Embedding** | Chunks are vectorized using a local embedding model and stored in Qdrant with payload metadata | `backend/embeddings/model.py`, `worker/job_handlers/embed_chunks.py` |
| **Retrieval** | User question is embedded, ANN vector search returns top-20 candidates from Qdrant filtered by session | `backend/agent/nodes.py → retrieve_chunks()` |
| **Reranking** | Cross-encoder rescores query-document pairs, narrows to top 3 | `backend/agent/nodes.py → rerank_chunks()`, `backend/reranker/model.py` |
| **Augmentation** | Retrieved documents are formatted with source references and injected into the LLM prompt | `backend/agent/prompts.py → GENERATE_ANSWER`, `nodes.py → _format_documents()` |
| **Generation** | LLM produces a grounded answer with inline citations like `[row:VA201301-0455]` | `backend/agent/nodes.py → generate_answer()` |

### ML (Machine Learning)

Two locally-hosted ML models run in-process — no external API calls for embeddings or reranking.

| Model | Type | Purpose | File |
|---|---|---|---|
| `BAAI/bge-small-en-v1.5` | SentenceTransformer (384-dim dense embeddings) | Query + document vectorization, semantic chunking breakpoints | `backend/embeddings/model.py` |
| `BAAI/bge-reranker-base` | CrossEncoder | Two-stage retrieval: rescores query-document pairs after ANN recall | `backend/reranker/model.py` |
| OpenAI `gpt-4o-mini` | LLM (via API) | Grading, query rewriting, answer generation, self-check scoring | `backend/agent/nodes.py` |

Both local models are lazy-loaded with `@lru_cache`, protected by async locks for thread safety, and share a HuggingFace cache volume across Docker containers (~400MB combined).

### Agentic AI

A **Corrective RAG Agent** implemented as a LangGraph `StateGraph` with autonomous decision-making and self-correction.

```
retrieve → rerank → grade_documents ──→ generate → self_check → END
                         │
                    (insufficient?)
                         │
                    rewrite_query → retrieve (loop, up to 2 retries)
                         │
                    (max retries?)
                         │
                    respond_insufficient → END
```

| Agentic capability | How it works | File |
|---|---|---|
| **Autonomous routing** | `_grade_router()` decides at runtime: proceed to generation, rewrite query, or give up — based on LLM-judged document sufficiency | `backend/agent/graph.py` |
| **Self-correction loop** | Agent loops `grade → rewrite → retrieve` up to 2 times, adapting search strategy based on what was retrieved | `backend/agent/graph.py` |
| **Reflection (self-check)** | After generating, the agent scores its own answer on faithfulness (0.0–1.0) and relevancy (0.0–1.0), producing a confidence label | `backend/agent/nodes.py → self_check()` |
| **Typed state machine** | `AgentState` TypedDict tracks session context, accumulated chunks, retry count, and intermediate results across all nodes | `backend/agent/graph.py → AgentState` |
| **Structured prompts** | All 4 LLM calls use `ChatPromptTemplate` with system/human message pairs, role definitions, and JSON output schemas | `backend/agent/prompts.py` |

### MLOps

Production infrastructure for deploying, monitoring, evaluating, and maintaining the ML system.

| Concern | Implementation | Files |
|---|---|---|
| **Containerization** | 7-service Docker Compose: API, worker, frontend, PostgreSQL, Redis, MinIO, Qdrant — with health checks on all infra services | `docker-compose.yml`, `Dockerfile.base`, `Dockerfile.api`, `Dockerfile.worker` |
| **CI/CD** | 4-stage GitHub Actions: lint (ruff) → test (pytest) → build (Docker images) → smoke-test (live health check) | `.github/workflows/ci-cd.yml` |
| **Job queue** | Async PostgreSQL-backed queue with `FOR UPDATE SKIP LOCKED` for safe concurrent job claiming, dispatched by a background worker | `worker/scheduler.py`, `worker/main.py` |
| **Benchmark evaluation** | Runs labeled Q&A pairs through the full RAG pipeline, measures retrieval hit rate, answer correctness, faithfulness, and relevancy | `worker/job_handlers/eval_benchmark.py`, `api/routes/eval.py` |
| **Continuous evaluation** | 20% of live `/ask` calls sampled — self-check scores logged to `eval_results` for drift monitoring | `api/routes/ask.py → _log_live_sample()` |
| **Session lifecycle** | TTL-based session expiry (7 days), periodic cleanup job every 15 min deletes expired Qdrant vectors, draft chunks, blobs | `worker/job_handlers/cleanup.py`, `worker/main.py` |
| **Model management** | Models configurable via env vars, lazy-loaded with caching, shared Docker volume for HuggingFace cache | `api/core/config.py`, `backend/embeddings/model.py`, `backend/reranker/model.py` |
| **Structured logging** | Every operation logged with context: `session_id`, `job_id`, `job_type`, timing, errors | `api/core/logging.py`, used throughout |
| **Test suite** | 58 pytest tests covering chunking, tabular split, PDF parsing, agent nodes (with mock assertions for message format), format detection | `tests/` |

## Architecture Decisions

- **Thin API, heavy worker:** All CPU/IO-intensive work (parsing, embedding, chunking) runs in a separate worker service. The API only validates, enqueues, and serves cached results.
- **Postgres job queue (not Celery):** `SELECT ... FOR UPDATE SKIP LOCKED` gives horizontally safe job claiming without an extra broker dependency.
- **Local embeddings + reranker:** No per-call cost for embeddings or reranking. Both models run in-process (~400MB combined).
- **Semantic chunking:** Embedding-based breakpoints produce more coherent chunks than fixed-size splitting, especially for mixed-format documents.
- **Narrative/categorical split:** For tabular data, only free-text fields are embedded. Short/enum columns become Qdrant payload filters — this avoids polluting the vector space with non-semantic data.
- **Honest "I don't know":** After 2 retry attempts, the agent returns an insufficient-context response rather than hallucinating.

## License

MIT
