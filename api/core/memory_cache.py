import json
import time
from typing import Any

_store: dict[str, tuple[str, float]] = {}


def _set(key: str, value: dict[str, Any], ttl: int) -> None:
    _store[key] = (json.dumps(value), time.time() + ttl)


def _get(key: str) -> dict[str, Any] | None:
    item = _store.get(key)
    if item is None:
        return None
    raw, expires_at = item
    if time.time() > expires_at:
        _store.pop(key, None)
        return None
    return json.loads(raw)


async def cache_job_status(job_id: str, status: dict[str, Any], ttl: int) -> None:
    _set(f"job:{job_id}", status, ttl)


async def get_cached_job_status(job_id: str) -> dict[str, Any] | None:
    return _get(f"job:{job_id}")


async def cache_session(session_id: str, data: dict[str, Any], ttl: int) -> None:
    _set(f"session:{session_id}", data, ttl)


async def get_cached_session(session_id: str) -> dict[str, Any] | None:
    return _get(f"session:{session_id}")


async def cache_upload_state(upload_id: str, data: dict[str, Any], ttl: int) -> None:
    _set(f"upload:{upload_id}", data, ttl)


async def get_upload_state(upload_id: str) -> dict[str, Any] | None:
    return _get(f"upload:{upload_id}")
