import asyncio
import time

from api.core.config import settings
from api.core.db import get_pool, run_migrations
from api.core.logging import logger
from api.core.qdrant_client import ensure_collection
from api.core.redis_client import get_redis
from worker.scheduler import claim_pending_jobs, dispatch_job

CLEANUP_INTERVAL_SECONDS = 15 * 60  # 15 minutes


async def _maybe_enqueue_cleanup(last_cleanup: float) -> float:
    now = time.monotonic()
    if now - last_cleanup < CLEANUP_INTERVAL_SECONDS:
        return last_cleanup
    try:
        from api.core.jobs import enqueue_job
        await enqueue_job("cleanup", {})
        logger.info("cleanup_job_enqueued_periodic")
    except Exception as exc:
        logger.warning("cleanup_enqueue_failed", error=str(exc))
    return now


async def run_worker() -> None:
    await get_pool()
    await run_migrations()
    await get_redis()
    await ensure_collection()

    logger.info("worker_started", worker_poll_interval=settings.worker_poll_interval_seconds)
    last_cleanup = 0.0

    while True:
        last_cleanup = await _maybe_enqueue_cleanup(last_cleanup)

        jobs = await claim_pending_jobs(settings.worker_batch_size)
        if not jobs:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
            continue

        await asyncio.gather(*(dispatch_job(job) for job in jobs))


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
