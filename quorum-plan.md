# Quorum — Agentic RAG Platform: Final Plan (v4)

**Scope:** RAG-only Q&A across CSV, Excel, PDF, and TXT uploads, for ~100
concurrent users, uploads up to 1GB. Built as an agentic pipeline (LangGraph)
with self-critique/retry, a local embedding model, Qdrant Cloud for vector
search, a cross-encoder reranker, and a dual-track evaluation system
(continuous LLM-as-judge + a labeled benchmark set) with results surfaced
both inline and on a dashboard.

**Architectural DNA carried over from the OneRay review:** thin API layer,
all heavy work in a separate worker service, Postgres-backed job queue with
row-locking for safe horizontal scaling, bounded TTLs everywhere, no
module-level mutable state, Pydantic contracts at every boundary.

**What's different from v3:** the Polars tool-calling agent is gone.
Everything is RAG. Vector storage moved from pgvector to Qdrant Cloud.
Chunking is semantic, not fixed-size. A reranker sits between retrieval and
generation. The agent is a LangGraph state machine with a self-critique loop,
not a single retrieve-then-generate call. An evaluation system — both
continuous and benchmark-based — is now a first-class part of the design,
not an afterthought.

---

## 1. System Architecture

```
Browser (Next.js frontend)
  |
  | HTTPS
  v
FastAPI gateway (thin — validation, auth, job enqueue, status, /ask, /eval)
  |
  |--- chunked upload ---> Blob Storage (GCS/S3): raw files
  |--- enqueue_job() ----> PostgreSQL: jobs table (durable queue)
  |--- session/status ---> Valkey/Redis: transient state, bounded TTL
  |--- /ask (synchronous, bounded latency) --------------------+
  |--- /eval (triggers benchmark job) ----> jobs table          |
                                                                  v
Worker service (N replicas, APScheduler + SKIP LOCKED claiming)   |
  |                                                                |
  | Ingestion jobs (per upload)                                    |
  v                                                                 |
Format dispatcher                                                   |
  |                                                                   |
  |-- CSV/Excel --> parse rows --> split narrative vs categorical      |
  |                  fields --> semantic-chunk narrative text            |
  |-- PDF --------> extract per-page text + tables --> semantic-chunk     |
  |                  narrative text; tables kept intact as markdown chunks |
  |-- TXT --------> extract full text --> semantic-chunk                   |
  v                                                                          |
Local embedding model (bge-small-en-v1.5) embeds each chunk                  |
  |                                                                           |
  v                                                                           |
Qdrant Cloud: chunk vector + payload (session_id, source_format,             |
  source_ref [page/row], categorical metadata for filtering)                 |
  |                                                                           |
  (ingestion job marked completed in Postgres + Redis)                       |
                                                                              v
                                                              LangGraph Agent (per /ask call)
                                                              ┌─────────────────────────────┐
                                                              │ 1. retrieve (embed question,  │
                                                              │    Qdrant top-15..20,          │
                                                              │    optional payload filter)      │
                                                              │ 2. rerank (cross-encoder          │
                                                              │    → top 3)                        │
                                                              │ 3. grade_documents (LLM judges      │
                                                              │    sufficiency)                       │
                                                              │      insufficient + retries left ──┐  │
                                                              │      │                              │  │
                                                              │      v                              │  │
                                                              │ 4. rewrite_query (LLM) ──────────────┘  │
                                                              │      loops back to (1)                   │
                                                              │      insufficient + no retries left       │
                                                              │      → respond_insufficient                │
                                                              │      sufficient → 5. generate answer         │
                                                              │      → 6. self_check (faithfulness/relevance,│
                                                              │           informational confidence score)     │
                                                              └─────────────────────────────────────────────┘
                                                              Graph state lives in-memory for the duration
                                                              of one /ask request — no persistence needed,
                                                              no violation of "no module-level mutable state"
                                                              since it's per-request local state.

Benchmark eval jobs (separate from live /ask) run the same agent against the
labeled Q&A set, compare retrieved source_ref + generated answer against
expected values, and write results to eval_runs/eval_results tables for the
dashboard.
```

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js 15 + TypeScript + Tailwind + TanStack Query** | polling/refetch UX for job status and eval dashboard is exactly what TanStack Query is for; mirrors OneRay's own frontend stack |
| API framework | FastAPI, `async def` everywhere | non-blocking I/O required at 100 concurrent users |
| Vector DB | **Qdrant Cloud (managed)** | native hybrid search + payload filtering, no self-host ops burden |
| Embeddings | **Local, open-source** (`bge-small-en-v1.5` via `sentence-transformers`) | no per-call cost; same model used for ingestion and query-time embedding via one shared module |
| Reranker | **Local cross-encoder** (`bge-reranker-base`) | improves top-3 precision after the fast vector search pass |
| Chunking | **Semantic chunking** (embedding-based breakpoints), format-aware | adaptive chunk boundaries; different rules for tabular narrative text vs. PDF prose vs. PDF tables |
| Agent orchestration | **LangGraph** | conditional retry loop (Corrective RAG pattern) needs real branching, not a linear chain |
| Durable state | PostgreSQL | jobs, sessions, uploads, labeled Q&A set, eval run results |
| Transient state | Valkey/Redis, bounded TTL | job status cache, session mapping, rate limiting |
| Blob storage | GCS (or S3) | raw uploaded files |
| Job queue | Postgres table + APScheduler + `SELECT ... FOR UPDATE SKIP LOCKED` | horizontally safe async ingestion without Celery |
| LLM | OpenAI `gpt-4o-mini` | generation, query rewriting, self-critique judging |
| Containerization | Docker, two images: `api`, `worker` | independent scaling |
| CI/CD | GitHub Actions: test → build → smoke-test → gated deploy | |
| Deployment | Cloud Run (`api`, `worker`) + Cloud SQL (Postgres) + Memorystore (Redis) + GCS + Qdrant Cloud | mirrors OneRay's production shape, sized for cost |

---

## 3. Repository Structure

```
quorum/
├── frontend/                        # Next.js app
│   ├── app/
│   │   ├── upload/page.tsx             # chunked upload UI
│   │   ├── chat/page.tsx                # /ask UI with confidence badges
│   │   └── eval/page.tsx                 # eval dashboard
│   ├── lib/api-client.ts               # apiUrl(), fetch wrappers
│   └── components/
├── api/                              # FastAPI gateway — thin
│   ├── main.py
│   ├── core/
│   │   ├── db.py                       # asyncpg pool
│   │   ├── cache.py                     # Redis client, TTL constants
│   │   ├── blob_store.py                 # GCS/S3 wrapper
│   │   ├── qdrant_client.py               # Qdrant connection + collection helpers
│   │   ├── jobs.py                         # enqueue_job(), status reads
│   │   └── config.py                        # pydantic-settings
│   ├── routes/
│   │   ├── uploads.py                   # chunked upload endpoints
│   │   ├── jobs.py                        # GET /jobs/{id}
│   │   ├── ask.py                          # POST /ask (invokes LangGraph)
│   │   ├── eval.py                          # POST /eval/run, GET /eval/runs
│   │   └── health.py
│   └── models/                        # Pydantic schemas
├── worker/
│   ├── main.py                          # APScheduler polling loop
│   ├── scheduler.py                       # job claiming, dispatch
│   └── job_handlers/
│       ├── ingest_tabular.py                # CSV/Excel: narrative/categorical split
│       ├── ingest_pdf.py                      # page text + table extraction
│       ├── ingest_txt.py                       # flat text
│       ├── run_eval_benchmark.py                # labeled Q&A benchmark job
│       └── cleanup.py                             # TTL sweep
├── backend/                          # pure logic, no FastAPI imports
│   ├── ingestion/
│   │   ├── detect_format.py
│   │   ├── tabular_split.py               # narrative vs. categorical field split
│   │   ├── pdf_parser.py                    # pdfplumber tables + pypdf text
│   │   └── chunker.py                         # semantic chunking, format-aware
│   ├── embeddings/
│   │   └── model.py                       # shared lazy-loaded embedding singleton
│   ├── reranker/
│   │   └── model.py                       # shared lazy-loaded cross-encoder singleton
│   └── agent/
│       ├── graph.py                       # LangGraph definition
│       ├── nodes.py                         # retrieve, rerank, grade, rewrite, generate, self_check
│       └── prompts.py                        # centralized prompt templates
├── tests/
│   ├── core/
│   ├── backend/                        # chunker, agent node unit tests
│   └── load/                            # Locust
├── db/migrations/
├── docker-compose.yml                 # api + worker + postgres + redis (Qdrant via cloud, or local qdrant/qdrant image for dev)
├── Dockerfile.api
├── Dockerfile.worker
├── Makefile
├── pyproject.toml
├── .github/workflows/ci-cd.yml
├── ARCHITECTURE_RULES.md
└── README.md
```

---

## 4. Data Model

### PostgreSQL

```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL,        -- ingest_tabular | ingest_pdf | ingest_txt | eval_benchmark | cleanup
    status TEXT NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL,
    result_ref TEXT,
    error TEXT,
    claimed_by TEXT,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_status_created ON jobs (status, created_at);

CREATE TABLE sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_format TEXT NOT NULL,       -- csv | xlsx | pdf | txt
    blob_key TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    chunk_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Labeled benchmark set (seeded from your uploaded sample files)
CREATE TABLE labeled_qa (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id),
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_source_ref TEXT,          -- e.g. "page:3" or "row:VA201301-0455"
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type TEXT NOT NULL,             -- 'benchmark' | 'live_sample'
    avg_retrieval_hit_rate FLOAT,
    avg_answer_correctness FLOAT,
    avg_faithfulness FLOAT,
    avg_answer_relevancy FLOAT,
    question_count INT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE eval_results (
    id SERIAL PRIMARY KEY,
    eval_run_id UUID REFERENCES eval_runs(id),
    labeled_qa_id INT REFERENCES labeled_qa(id),
    generated_answer TEXT,
    retrieved_source_refs TEXT[],
    retrieval_hit BOOLEAN,               -- did top-3 include expected_source_ref?
    answer_correctness FLOAT,             -- LLM-judge score, 0-1
    faithfulness FLOAT,
    answer_relevancy FLOAT,
    retries_used INT
);
```

### Qdrant collection schema

```
collection: quorum_chunks
vector: 384-dim (bge-small-en-v1.5 output size), cosine distance
payload:
  session_id: keyword
  source_format: keyword          # csv | xlsx | pdf | txt
  source_ref: keyword              # "page:3" | "row:VA201301-0455" | "row:12"
  chunk_text: text                  # stored for retrieval-time display/citation
  # only for CSV/Excel rows:
  product: keyword (optional)
  country: keyword (optional)
  status: keyword (optional)
  # arbitrary other categorical fields as needed, added at ingestion time
```
Payload fields double as **metadata filters** — e.g. a question mentioning
"Protege RX" can filter to `product = "PROTEGE RX CAROTID STENT SYSTEM"`
before the vector search narrows further, which is exactly the capability
that justified choosing Qdrant over pgvector.

---

## 5. Ingestion Pipeline (format-aware, semantic chunking)

### CSV / Excel
1. Parse with Polars (`read_csv` / `read_excel`) purely as an ingestion-time
   utility — **not** exposed as a query-time tool anymore, since the agent
   is RAG-only now.
2. **Split fields into narrative vs. categorical**, per column heuristics
   (long free-text columns like `Event Description`, `Summary of
   Investigation Results` → narrative; short/enum-like columns like
   `Product`, `Country`, `Status` → categorical metadata).
3. For each row: concatenate narrative fields into chunk text; if that text
   is long, semantic-chunk it into sub-chunks. Attach all categorical fields
   as Qdrant payload on every resulting chunk, plus `source_ref = "row:<id>"`
   using a natural row identifier if one exists (e.g. complaint ID),
   otherwise a generated row index.
4. Purely numeric spreadsheets with no meaningful narrative text are a known
   limitation of the RAG-only design — flagged explicitly in
   `ARCHITECTURE_RULES.md`'s known-limitations section, not silently
   pretended away.

### PDF
1. Extract text **per page** (`pypdf`), preserving page number.
2. Attempt table extraction (`pdfplumber`) per page; where a clean table is
   found (e.g. a revision history table, a step-by-step procedure table),
   render it as a markdown table and treat the **whole table as one chunk**
   — never semantic-split a table, since that breaks rows apart from their
   headers.
3. Remaining prose per page is semantic-chunked normally.
4. Every chunk's payload includes `source_ref = "page:<n>"`.
5. Scanned/image-only PDFs with no extractable text are explicitly
   unsupported for v1 (surfaced as a job failure, not a silent empty
   result) — OCR is a stated future extension, not something we pretend to
   support.

### TXT
1. Extract full text as-is.
2. Semantic-chunk directly, no page concept — `source_ref = "chunk:<n>"`.

### Chunking mechanics
- Uses LangChain's `SemanticChunker`, backed by the same local embedding
  model used for retrieval (consistency matters — chunking with one model
  and retrieving with another would be a subtle, hard-to-debug bug).
- Breakpoint threshold: percentile-based (standard default), tunable per
  format if benchmark results show a format underperforming.

---

## 6. The Agent: LangGraph Corrective RAG

### Nodes

**`retrieve`** — embeds the user's question with the same local embedding
model, queries Qdrant for the top ~15-20 candidates (optionally with a
payload filter if the question clearly references a specific product,
country, etc. — detected via a lightweight keyword/entity check, not a
separate ML model).

**`rerank`** — cross-encoder scores each (question, chunk) pair, keeps the
top 3.

**`grade_documents`** — one LLM call: "given this question and these 3
chunks, is there enough information to answer confidently?" Returns a
sufficient/insufficient judgment with brief reasoning.

**`rewrite_query`** (conditional) — only reached if `grade_documents` says
insufficient *and* retries remain. An LLM call rewrites the question
(broadens terms, adds synonyms, or reframes) and loops back to `retrieve`.

**`respond_insufficient`** (conditional) — reached if insufficient and no
retries remain. Returns an honest "I don't have enough information to answer
this confidently" rather than a guess — this is the behavior that makes the
whole retry design worth having.

**`generate`** — LLM produces the final answer grounded in the top-3 chunks,
with inline citations to `source_ref` values.

**`self_check`** — one more LLM call scoring faithfulness (does the answer
contradict the retrieved context?) and answer relevancy (does it actually
address the question?). This score is **informational for v1** — it feeds
the confidence badge shown in the UI, but does not itself trigger another
retry loop (bounding total latency/cost per question). This is a deliberate
simplification worth stating explicitly rather than pretending the system
self-corrects indefinitely.

### Retry policy
- Max 2 retries (3 total attempts) through `retrieve → rerank → grade`.
- Each retry costs roughly 2-3 extra LLM calls plus a Qdrant round-trip —
  bounding this is a real latency/cost control, not just a nice-to-have.

### Why `/ask` stays synchronous (not job-queued)
Unlike file ingestion, `/ask` is a conversational interaction — users expect
a direct response. A worst-case run (max retries + generate + self-check) is
on the order of single-digit seconds, which is within a reasonable HTTP
request lifetime. This is different from R4's "full-dataset work must be a
job" rule — `/ask` operates on already-embedded, already-small (top-3)
context, not a full dataset, so it doesn't trigger that rule. Graph state
lives in memory only for the duration of one request; nothing here needs
Redis/Postgres persistence.

**Scale implication:** at 100 concurrent users each potentially running
multi-call agent turns, the API needs a bounded concurrency guard (an
`asyncio.Semaphore` around outbound OpenAI calls) so a burst of simultaneous
`/ask` requests doesn't blow through OpenAI rate limits and cause cascading
timeouts. This is a load-test-verify item, not just a code review item.

---

## 7. API Design

### `POST /uploads/init`, `PUT /uploads/{id}/chunk/{n}`, `POST /uploads/{id}/complete`
Unchanged from v3 — chunked upload straight to blob storage, format detection
by magic bytes, enqueues the appropriate ingestion job.

### `GET /jobs/{job_id}`
Unchanged pattern — status polling for ingestion and benchmark jobs alike.

### `POST /ask`
```json
{ "session_id": "s_91cd", "question": "What was the deployment force recorded in complaint VA201301-0455?" }
```
```json
{
  "answer": "5.51 lbs of deployment force was generated, exceeding the ≤3 lbs specification.",
  "citations": [{ "source_ref": "row:VA201301-0455", "excerpt": "..." }],
  "confidence": {
    "label": "high",
    "faithfulness": 0.94,
    "answer_relevancy": 0.91
  },
  "retries_used": 0,
  "execution_time_ms": 2210
}
```
The `confidence` block is the inline badge the frontend renders next to the
answer.

### `POST /eval/run`
Triggers a benchmark job over the full `labeled_qa` set for a given session
or globally. Returns a `job_id`; results land in `eval_runs`/`eval_results`.

### `GET /eval/runs`
Returns historical benchmark runs for the dashboard — retrieval hit rate,
answer correctness, faithfulness, answer relevancy over time, so you can see
whether a chunking or prompt change made things better or worse.

### `GET /health`, `GET /metrics`
Unchanged pattern, extended to check Qdrant connectivity alongside Postgres,
Redis, and blob storage.

---

## 8. Evaluation System

**Continuous (every live `/ask`):** the `self_check` node's faithfulness and
answer-relevancy scores are logged to `eval_results` as `run_type =
'live_sample'` (sampled, not necessarily every single request, to control
judge-LLM cost) and shown inline as the confidence badge.

**Benchmark (on demand or scheduled):** runs the full labeled `labeled_qa`
set through the real agent pipeline, computing:
- **Retrieval hit rate** — did the reranked top-3 include a chunk whose
  `source_ref` matches `expected_source_ref`? (Objective, no LLM judge
  needed — this is the metric to trust most.)
- **Answer correctness** — LLM-as-judge comparing the generated answer
  against `expected_answer` (0-1 score).
- **Faithfulness / answer relevancy** — same as the continuous metrics,
  computed against the benchmark questions specifically.

**Dashboard (`/eval` page in the frontend):** a table of runs over time plus
a per-question drill-down (which questions the retrieval missed, which
answers scored low on correctness) — this is what turns "I built RAG" into
"I measured and improved RAG," a materially stronger interview claim.

**Seed data:** the 12 Q&A pairs drafted from your uploaded PDF and CSV are
the starting `labeled_qa` rows — extend this set as you add more sample
documents.

---

## 9. Edge Cases — updated for this design

### Chunking / ingestion
| Case | Handling |
|---|---|
| Semantic chunker produces a single giant chunk (no clear topic breaks found) | Cap maximum chunk size as a hard ceiling even under semantic chunking, to bound embedding/prompt cost |
| CSV row with an empty/near-empty narrative field | Skip chunk creation for that row rather than embedding near-empty text; still index categorical metadata if useful for filtering |
| PDF table spans multiple pages | Detect continuation (matching headers) and merge into one chunk rather than splitting the table awkwardly across page-based chunks |
| Chunking/embedding model mismatch after a model upgrade | Track the embedding model version in Qdrant payload; a model change requires re-embedding the whole collection, not incremental patching |

### Retrieval / agent
| Case | Handling |
|---|---|
| Retrieval returns confident-looking but wrong chunks (semantic false positive) | This is exactly what `grade_documents` exists to catch — but it's an LLM judgment call, not infallible; the benchmark's retrieval-hit-rate metric is the real check on this over time |
| Question references a product/entity not in the payload metadata | Filter step should degrease gracefully to unfiltered vector search rather than returning zero results |
| Runaway retry loop cost | Hard-capped at 2 retries; log `retries_used` per request so cost/latency patterns are visible in `/metrics` |
| Reranker and embedding model disagree sharply on ranking | Expected and healthy — that's the point of a second-stage reranker; don't "fix" this by removing one of the two signals |

### Evaluation
| Case | Handling |
|---|---|
| LLM-judge scoring is itself inconsistent between runs | Use a fixed, low-temperature judge prompt and report scores as trends over multiple runs, not single-run absolutes |
| Labeled set is small (12-20 questions) | Explicitly disclosed as a benchmark, not a statistically rigorous evaluation — still far better than no measurement, and expandable over time |
| Benchmark job itself fails partway | Same job-retry/attempts-cap pattern as ingestion jobs (§7.2 of the rules file) |

### Scale (100 concurrent users)
(Carried forward from v3, plus:)
- Qdrant Cloud request quota/rate limits at 100 concurrent users doing
  retrieval — check your Qdrant Cloud tier's request-per-second limits before
  load testing, since this is now a third external dependency (alongside
  OpenAI) that can rate-limit you under load.
- Local embedding/reranker models running in-process in both API (query-time)
  and worker (ingestion-time) means both containers need enough memory for
  model weights (~200-400MB combined) — size Cloud Run memory limits
  accordingly, this is a real constraint, not a rounding error.

---

## 10. Frontend (Next.js)

```
frontend/app/
├── upload/page.tsx      # drag-drop chunked upload, shows job status via
│                           TanStack Query polling GET /jobs/{id}
├── chat/page.tsx          # ask questions, renders answer + citations +
│                             confidence badge (color-coded from /ask response)
└── eval/page.tsx            # dashboard: eval_runs over time (Recharts line
                                chart), per-question drill-down table
```
- **TanStack Query** handles all polling/refetching (job status, eval runs)
  with sane cache invalidation, rather than hand-rolled `setInterval` calls.
- **Tailwind + Radix UI** for consistent styling and accessible components
  (dialogs for citation detail, tooltips for score explanations).
- Confidence badge color scheme: green (faithfulness + relevancy both high),
  yellow (one metric borderline), red (low, or `respond_insufficient` was
  triggered) — makes the self-check score legible at a glance rather than
  just a raw number.

---

## 11. How to Run — Local Development

```bash
git clone <your-repo-url>
cd quorum
cp .env.example .env      # OPENAI_API_KEY, QDRANT_URL, QDRANT_API_KEY, etc.
uv sync
make setup
make up                    # postgres + redis + api + worker (+ local qdrant
                              for dev, pointed at Qdrant Cloud in prod)
make migrate-apply
```
- API docs: `http://localhost:8000/docs`
- Frontend: `cd frontend && pnpm install && pnpm dev` → `http://localhost:3000`
- Seed the labeled eval set:
  ```bash
  uv run python scripts/seed_labeled_qa.py --file db/seed/labeled_qa.json
  ```
- Run a benchmark manually:
  ```bash
  curl -X POST http://localhost:8000/eval/run
  ```
- Tests:
  ```bash
  make lint
  uv run pytest tests/core tests/backend -v
  uv run locust -f tests/load/locustfile.py --headless -u 100 -r 10 --run-time 5m
  ```

---

## 12. CI/CD & Deployment

Unchanged shape from v3 (§9-10 there): GitHub Actions test → build (`api`,
`worker` images) → smoke-test (`/health` now also checks Qdrant) → gated
deploy to Cloud Run. Cloud SQL (Postgres), Memorystore (Redis), and GCS
remain as before; **Qdrant Cloud replaces the pgvector extension** as an
external managed dependency, configured via environment variables
(`QDRANT_URL`, `QDRANT_API_KEY`) rather than a Cloud Run-hosted service.

---

## 13. Realistic Build Timeline

| Phase | Time | Output |
|---|---|---|
| Repo scaffold, Postgres/Redis/Qdrant (dev) in Compose | 1h | `make up` works |
| Chunked upload + blob storage + format detection | 2h | uploads flow end-to-end |
| Jobs table + worker with SKIP LOCKED claiming | 2h | ingestion jobs process safely |
| Format-aware parsing + narrative/categorical split | 2h | CSV/Excel/PDF/TXT all parse correctly |
| Semantic chunking + embedding + Qdrant indexing | 2h | chunks searchable in Qdrant with payload filters |
| Reranker integration | 1h | top-3 reranked results verified |
| LangGraph agent (retrieve/rerank/grade/rewrite/generate/self_check) | 3h | `/ask` answers with retry logic working |
| Eval system (continuous + benchmark + seed labeled set) | 2.5h | `/eval/run` produces real numbers against your uploaded files |
| Frontend (Next.js: upload, chat, eval dashboard) | 3h | usable UI, not just `/docs` |
| Tests + load test | 2h | pytest + Locust against realistic file mix |
| CI/CD + Cloud Run deploy | 2h | gated pipeline live |

**Total: ~22-24 hours** — this is now a complete agentic RAG platform with a
measurement layer, not a weekend script. That's the honest scope for what's
been designed here.

---

## 14. What to say about this project in an interview

> "I built an agentic RAG platform that answers questions over CSV, Excel,
> PDF, and TXT uploads — including messy real-world data like a medical
> device complaint log with 78 columns where only two or three were actually
> narrative text worth embedding, so I split narrative fields from
> categorical metadata and used the categorical fields as Qdrant payload
> filters instead of embedding them. The agent is a LangGraph state machine,
> not a single retrieve-and-generate call: it grades its own retrieved
> context, rewrites the query and retries up to twice if the context looks
> insufficient, and honestly says it doesn't know rather than guessing once
> retries are exhausted. I added a cross-encoder reranker between vector
> search and generation to improve precision, and I built a real evaluation
> layer — a labeled benchmark set with known answers and source references,
> so I can report an actual retrieval hit rate and answer-correctness score,
> not just a vibe that the demo looked good. Everything runs through the
> same production-shaped infrastructure as the rest of the platform: a
> Postgres-backed job queue safe across multiple worker replicas, bounded
> TTLs, and a gated CI/CD pipeline to Cloud Run."

That's a genuinely complete GenAI/AI Engineer story — ML (embeddings +
reranker), agent (LangGraph decision-making), and measurement (a real eval
system), all sitting on production-grade infrastructure.
