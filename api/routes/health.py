from fastapi import APIRouter

from api.core.blob_store import check_blob_store
from api.core.config import settings
from api.core.db import get_pool
from api.core.qdrant_client import check_qdrant
from api.core.redis_client import get_redis
from api.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    postgres_ok = False
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        postgres_ok = True
    except Exception:
        pass

    if not settings.redis_enabled:
        redis_ok = True
    else:
        redis_ok = False
        try:
            redis = await get_redis()
            redis_ok = (await redis.ping()) is True
        except Exception:
            pass

    blob_ok = await check_blob_store()
    qdrant_ok = await check_qdrant()

    all_ok = postgres_ok and redis_ok and blob_ok and qdrant_ok
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        postgres=postgres_ok,
        redis=redis_ok,
        blob_store=blob_ok,
        qdrant=qdrant_ok,
    )
