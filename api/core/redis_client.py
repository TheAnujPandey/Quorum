import json
from typing import Any

import redis.asyncio as aioredis

from api.core.cache import JOB_STATUS_TTL, SESSION_TTL, UPLOAD_STATE_TTL
from api.core.config import settings

_redis: aioredis.Redis | None = None
_redis_available: bool | None = None


async def _use_redis() -> bool:
    global _redis_available
    if not settings.redis_enabled:
        return False
    if _redis_available is not None:
        return _redis_available
    try:
        redis = await get_redis()
        await redis.ping()
        _redis_available = True
    except Exception:
        _redis_available = False
    return _redis_available


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis, _redis_available
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    _redis_available = None


async def cache_job_status(job_id: str, status: dict[str, Any]) -> None:
    if await _use_redis():
        redis = await get_redis()
        await redis.setex(f"job:{job_id}", JOB_STATUS_TTL, json.dumps(status))
        return
    from api.core.memory_cache import cache_job_status as mem_cache_job_status

    await mem_cache_job_status(job_id, status, JOB_STATUS_TTL)


async def get_cached_job_status(job_id: str) -> dict[str, Any] | None:
    if await _use_redis():
        redis = await get_redis()
        raw = await redis.get(f"job:{job_id}")
        if raw is None:
            return None
        return json.loads(raw)
    from api.core.memory_cache import get_cached_job_status as mem_get_job_status

    return await mem_get_job_status(job_id)


async def cache_session(session_id: str, data: dict[str, Any]) -> None:
    if await _use_redis():
        redis = await get_redis()
        await redis.setex(f"session:{session_id}", SESSION_TTL, json.dumps(data))
        return
    from api.core.memory_cache import cache_session as mem_cache_session

    await mem_cache_session(session_id, data, SESSION_TTL)


async def get_cached_session(session_id: str) -> dict[str, Any] | None:
    if await _use_redis():
        redis = await get_redis()
        raw = await redis.get(f"session:{session_id}")
        if raw is None:
            return None
        return json.loads(raw)
    from api.core.memory_cache import get_cached_session as mem_get_session

    return await mem_get_session(session_id)


async def cache_upload_state(upload_id: str, data: dict[str, Any]) -> None:
    if await _use_redis():
        redis = await get_redis()
        await redis.setex(f"upload:{upload_id}", UPLOAD_STATE_TTL, json.dumps(data))
        return
    from api.core.memory_cache import cache_upload_state as mem_cache_upload_state

    await mem_cache_upload_state(upload_id, data, UPLOAD_STATE_TTL)


async def get_upload_state(upload_id: str) -> dict[str, Any] | None:
    if await _use_redis():
        redis = await get_redis()
        raw = await redis.get(f"upload:{upload_id}")
        if raw is None:
            return None
        return json.loads(raw)
    from api.core.memory_cache import get_upload_state as mem_get_upload_state

    return await mem_get_upload_state(upload_id)
