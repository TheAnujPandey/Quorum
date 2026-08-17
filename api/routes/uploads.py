from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request

from api.core.blob_store import complete_multipart_upload, create_multipart_upload, upload_part
from api.core.config import settings
from api.core.db import get_pool
from api.core.logging import logger
from api.core.redis_client import cache_session, cache_upload_state, get_upload_state
from api.models.schemas import (
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
)
from backend.ingestion.detect_format import detect_format_from_filename

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/init", response_model=UploadInitResponse)
async def init_upload(body: UploadInitRequest) -> UploadInitResponse:
    upload_id = uuid4()
    session_id = uuid4()
    blob_key = f"sessions/{session_id}/{body.filename}"

    multipart_id = await create_multipart_upload(blob_key, body.content_type)

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (session_id, source_format, blob_key, qdrant_collection, upload_status, expires_at)
            VALUES ($1, 'unknown', $2, $3, 'uploading', $4)
            """,
            session_id,
            blob_key,
            settings.qdrant_collection,
            expires_at,
        )

    await cache_upload_state(
        str(upload_id),
        {
            "upload_id": str(upload_id),
            "session_id": str(session_id),
            "blob_key": blob_key,
            "multipart_id": multipart_id,
            "filename": body.filename,
            "content_type": body.content_type,
            "parts": [],
        },
    )
    await cache_session(
        str(session_id),
        {"session_id": str(session_id), "blob_key": blob_key, "upload_status": "uploading"},
    )

    logger.info("upload_initiated", upload_id=str(upload_id), session_id=str(session_id))
    return UploadInitResponse(
        upload_id=upload_id,
        session_id=session_id,
        chunk_size=settings.upload_chunk_size_bytes,
    )


@router.put("/{upload_id}/chunk/{chunk_number}")
async def upload_chunk(upload_id: UUID, chunk_number: int, request: Request) -> dict:
    state = await get_upload_state(str(upload_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    data = await request.body()
    etag = await upload_part(
        state["blob_key"],
        state["multipart_id"],
        chunk_number,
        data,
    )
    state["parts"].append({"PartNumber": chunk_number, "ETag": etag})
    await cache_upload_state(str(upload_id), state)
    return {"chunk_number": chunk_number, "received_bytes": len(data)}


@router.post("/{upload_id}/complete", response_model=UploadCompleteResponse)
async def complete_upload(upload_id: UUID) -> UploadCompleteResponse:
    """Upload only — does not start chunking/embedding. Client calls /sessions/{id}/chunk next."""
    state = await get_upload_state(str(upload_id))
    if state is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    parts = sorted(state["parts"], key=lambda p: p["PartNumber"])
    if not parts:
        raise HTTPException(status_code=400, detail="No chunks uploaded")

    await complete_multipart_upload(state["blob_key"], state["multipart_id"], parts)

    source_format = detect_format_from_filename(state["filename"])
    if source_format not in ("csv", "xlsx", "pdf", "txt"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {source_format}")

    session_id = UUID(state["session_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET source_format = $1, upload_status = 'uploaded' WHERE session_id = $2",
            source_format,
            session_id,
        )

    await cache_session(
        str(session_id),
        {
            "session_id": str(session_id),
            "blob_key": state["blob_key"],
            "upload_status": "uploaded",
            "source_format": source_format,
        },
    )

    logger.info(
        "upload_completed",
        upload_id=str(upload_id),
        session_id=str(session_id),
        source_format=source_format,
    )
    return UploadCompleteResponse(
        session_id=session_id,
        job_id=None,
        source_format=source_format,
        upload_status="uploaded",
    )
