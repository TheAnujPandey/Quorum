from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException

from api.core.jobs import get_job
from api.core.redis_client import cache_job_status, get_cached_job_status
from api.models.schemas import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: UUID) -> JobResponse:
    cached = await get_cached_job_status(str(job_id))
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    merged = {**job}
    if cached and job["status"] == "running":
        merged["stage"] = cached.get("stage") or merged.get("stage")
        merged["progress_pct"] = cached.get("progress_pct")
        merged["message"] = cached.get("message")
    elif cached and job["status"] == "completed":
        merged["stage"] = "done"
        merged["progress_pct"] = 100
        merged["message"] = cached.get("message") or "Complete"
    await cache_job_status(str(job_id), merged)
    return JobResponse(
        id=UUID(merged["id"]),
        job_type=merged["job_type"],
        status=merged["status"],
        stage=merged.get("stage"),
        progress_pct=merged.get("progress_pct"),
        message=merged.get("message"),
        payload=merged["payload"],
        result_ref=merged.get("result_ref"),
        error=merged.get("error"),
        attempts=merged["attempts"],
        created_at=datetime.fromisoformat(merged["created_at"]),
        updated_at=datetime.fromisoformat(merged["updated_at"]),
    )
