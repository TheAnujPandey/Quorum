import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.blob_store import ensure_bucket
from api.core.config import settings
from api.core.db import _use_sqlite, close_pool, get_pool, run_migrations
from api.core.logging import logger
from api.core.qdrant_client import close_qdrant, ensure_collection
from api.core.redis_client import close_redis, get_redis
from api.routes import ask, config, eval, health, jobs, sessions, uploads


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await run_migrations()
    await ensure_bucket()
    await get_redis()
    await ensure_collection()

    from backend.embeddings.model import embed_texts
    from backend.reranker.model import rerank_pairs

    async def _warmup() -> None:
        try:
            await asyncio.to_thread(embed_texts, ["warmup"])
            logger.info("embedding_model_warmed")
        except Exception as exc:
            logger.warning("embedding_model_warmup_failed", error=str(exc))
        try:
            await asyncio.to_thread(rerank_pairs, "warmup", ["warmup"])
            logger.info("reranker_model_warmed")
        except Exception as exc:
            logger.warning("reranker_model_warmup_failed", error=str(exc))

    asyncio.create_task(_warmup())

    worker_task: asyncio.Task | None = None
    if settings.run_worker_in_api:
        from worker.scheduler import claim_pending_jobs, dispatch_job, fail_stale_jobs

        await fail_stale_jobs()

        if _use_sqlite():
            logger.info("sqlite_inline_jobs", detail="jobs run immediately on enqueue; no poll loop")
        else:
            async def _worker_loop() -> None:
                logger.info("worker_started", worker_poll_interval=settings.worker_poll_interval_seconds)
                while True:
                    try:
                        jobs = await claim_pending_jobs(settings.worker_batch_size)
                        if not jobs:
                            await asyncio.sleep(settings.worker_poll_interval_seconds)
                            continue
                        await asyncio.gather(*(dispatch_job(job) for job in jobs))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("worker_loop_error")
                        await asyncio.sleep(settings.worker_poll_interval_seconds)

            worker_task = asyncio.create_task(_worker_loop())

    yield

    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    await close_qdrant()
    await close_redis()
    await close_pool()


app = FastAPI(title="Quorum API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(config.router)
app.include_router(uploads.router)
app.include_router(sessions.router)
app.include_router(jobs.router)
app.include_router(ask.router)
app.include_router(eval.router)
