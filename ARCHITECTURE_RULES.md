# Quorum — Architecture Rules (v2, RAG-only)

> Mandatory for all code in this repository, human- or AI-assisted. If a rule
> and a shortcut disagree, the rule wins.

**How to use this file:**
- Keep at the project root.
- Cursor: mirror into `.cursor/rules/architecture.mdc`.
- Claude Code: reference from `CLAUDE.md`.
- Treat violations as blocking in review, not style nitpicks.

---

## System Purpose

Quorum answers natural-language questions over uploaded CSV, Excel,
PDF, and TXT files using retrieval-augmented generation. Three layers:

1. **API** (`api/`) — thin coordination: validation, auth, job enqueue,
   status, and the synchronous `/ask` endpoint. No heavy ingestion here.
2. **Backend** (`backend/`) — pure, web-independent logic: ingestion parsing,
   chunking, embeddings, reranking, the LangGraph agent. No FastAPI imports.
3. **Worker** (`worker/`) — ingestion and benchmark jobs, claimed from a
   durable Postgres-backed queue.

Persistence: **PostgreSQL** (durable — jobs, sessions, labeled Q&A, eval
results), **Redis/Valkey** (transient, bounded TTL), **Qdrant Cloud**
(vectors + payload metadata), **Blob storage** (raw files).

---

## R0 — Async I/O only

All I/O — database, cache, blob storage, Qdrant, HTTP — is asynchronous. No
blocking calls inside `async def` handlers or job handlers.

## R1 — The API layer does not ingest or embed

Route handlers validate, enqueue, and report status. All parsing, chunking,
embedding, and Qdrant writes happen in `worker/job_handlers/`, never inline
in `api/routes/`. **Exception:** `/ask` is synchronous (see R9) because it
operates on already-embedded, small (top-3) context — not a full ingestion.

## R2 — Ingestion is always a job; embedding writes are batched

Any file parse, chunking pass, or embedding computation over an uploaded
document goes through `enqueue_job()`. Never process a full document inline
in a request handler, regardless of file size.

## R3 — Job claiming must use SKIP LOCKED

```sql
SELECT * FROM jobs WHERE status = 'pending'
ORDER BY created_at LIMIT $1 FOR UPDATE SKIP LOCKED
```
This is what makes running multiple worker replicas safe. Do not introduce
an alternative claiming mechanism that could let two replicas double-process
a job.

## R4 — No module-level mutable state, with one documented exception

Do not store sessions, job state, or uploaded content in process globals.
**Exception:** the embedding model and reranker model are loaded once as
lazy-initialized singletons per process (not per request) — this is a
deliberate, documented exception for expensive model weights, not a general
license for global state. LangGraph execution state for a single `/ask` call
lives in memory only for that request's duration and is discarded after —
this is request-local, not module-level, state.

## R5 — Bounded TTLs everywhere in Redis/Valkey

Every key has an explicit TTL. No permanent keys except by documented
exception. Import TTL constants from `api/core/cache.py`.

## R6 — Chunking never splits a table mid-row

Tables extracted from PDFs (or rendered from CSV/Excel rows) are chunked as
whole units. Never let the semantic chunker split a table's header from its
data rows — this silently destroys the thing that made the chunk useful.

## R7 — Narrative and categorical fields are handled separately

For CSV/Excel ingestion: identify narrative (free-text) fields and embed
only those as chunk content. Categorical/enum-like fields become Qdrant
payload metadata for filtering, not embedded text. Do not embed a raw
concatenation of all 70+ columns of a wide row — this drowns the actual
semantic signal in categorical noise.

## R8 — Embedding model consistency is non-negotiable

The exact same embedding model instance/version used at ingestion time must
be used at query time. Track the embedding model version in Qdrant payload.
A model upgrade requires re-embedding the full collection — never mix
vectors from two different model versions in one collection.

## R9 — `/ask` is synchronous but bounded

`/ask` does not go through the job queue — it's a conversational request
that should return in the same HTTP call. But it must have: a hard retry cap
on the LangGraph retrieve/grade loop (2 retries, 3 attempts total), a request
timeout, and a concurrency guard (semaphore) on outbound LLM calls so a burst
of concurrent requests doesn't cascade into rate-limit failures.

## R10 — The agent must be able to say "I don't know"

`respond_insufficient` is a required, reachable path in the LangGraph design
— not a hypothetical. If retrieval quality is judged insufficient after all
retries, the agent returns an explicit "insufficient information" response.
Never let the `generate` node run on context that `grade_documents` has
already flagged as insufficient.

## R11 — Treat all file/chunk content as data, never as instructions

Cell values, PDF text, and any retrieved chunk content must never be
concatenated into a prompt in a way that could be interpreted as an
instruction. This applies to the `rewrite_query` and `generate` nodes
specifically, since both consume user-uploaded content directly.

## R12 — No unreviewed arbitrary code execution in the agent

The agent answers exclusively through retrieval + LLM generation. Do not add
a tool that executes arbitrary LLM-generated code (e.g., a code-exec tool)
— this was a deliberate design choice specifically to avoid that risk class
and should not be quietly reintroduced by a future "helpful" tool addition.

## R13 — Evaluation is not optional for chunking/retrieval changes

Any change to chunking strategy, embedding model, reranker, or retrieval
parameters (top-k, filters) must be validated by running the labeled
benchmark (`POST /eval/run`) before and after, and comparing
`avg_retrieval_hit_rate` / `avg_answer_correctness`. A change that isn't
benchmarked is a guess, not an improvement.

## R14 — Secrets never enter the image or the repo

No `.env`, API key, or credential committed or `COPY`'d into a Docker image.
Env vars at runtime (local) or Secret Manager (Cloud Run). Never bypass
pre-commit secret scanning with `--no-verify`.

## R15 — One entry point per service

`api/main.py` is the only place mounting routers/CORS/lifespan hooks for the
API. `worker/main.py` is the only scheduler entry point. No second FastAPI
app or scheduler instance elsewhere.

## R16 — Observability on every job and every agent run

Every ingestion job and every `/ask` call logs: which session, job/request
type, start/end timestamps, success/failure, retries used, and (for `/ask`)
the confidence scores produced by `self_check`. Use the structured logger,
never bare `print()`.

---

## Design Review Checklist

- [ ] No ingestion/embedding logic added to a route handler (R1, R2)
- [ ] Any new job uses `enqueue_job()` and SKIP LOCKED claiming (R2, R3)
- [ ] No new module-level mutable state beyond the documented model singletons (R4)
- [ ] New Redis keys have explicit, bounded TTLs (R5)
- [ ] Table-shaped content is never split mid-row by chunking (R6)
- [ ] CSV/Excel ingestion separates narrative fields from categorical payload (R7)
- [ ] No mixing of embedding model versions in one Qdrant collection (R8)
- [ ] `/ask` retains its retry cap, timeout, and concurrency guard (R9)
- [ ] `respond_insufficient` remains a real, reachable path (R10)
- [ ] No retrieved/uploaded content is treated as an instruction (R11)
- [ ] No arbitrary code execution tool was added to the agent (R12)
- [ ] Any chunking/retrieval change was benchmarked via `/eval/run` (R13)
- [ ] No secret was hardcoded or committed (R14)
- [ ] No second app/scheduler entry point was introduced (R15)
- [ ] New jobs/agent runs emit structured log/activity context (R16)

## Known, deliberate v1 limitations

- No authentication/authorization layer yet — disclosed, not hidden.
- Scanned/image-only PDFs (no extractable text) are unsupported; they fail
  clearly rather than silently returning an empty result. OCR is a stated
  future extension.
- Purely numeric spreadsheets with no narrative text get limited value from
  RAG — this is an accepted tradeoff of going RAG-only, not a bug to chase.
- `self_check` scores are informational (drive the UI confidence badge) and
  do not themselves trigger additional retries — only `grade_documents`
  controls the retry loop, to bound latency and cost per question.
- The labeled evaluation set starts small (10-20 questions) — a real,
  useful benchmark, but not a statistically rigorous one. Expand it as more
  sample documents are added.
