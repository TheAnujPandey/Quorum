"""End-to-end ingest wizard test: upload -> chunk -> preview -> embed."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "db" / "seed" / "sample_complaints.csv"
BASE = "http://127.0.0.1:8000"


def req(method: str, path: str, data: bytes | None = None, content_type: str | None = None) -> dict | str:
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            if not body:
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def poll_job(job_id: str, timeout_s: float = 60) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = req("GET", f"/jobs/{job_id}")
        status = last.get("status")
        print(
            f"  job {job_id[:8]} status={status} stage={last.get('stage')} "
            f"pct={last.get('progress_pct')} msg={last.get('message')}"
        )
        if status in {"completed", "failed"}:
            return last
        time.sleep(0.5)
    raise TimeoutError(f"job {job_id} still {last.get('status')} after {timeout_s}s: {last}")


def main() -> int:
    health = req("GET", "/health")
    print("health:", health)
    if health.get("status") != "ok":
        print("API is not healthy")
        return 1

    csv_bytes = CSV_PATH.read_bytes()
    init = req(
        "POST",
        "/uploads/init",
        json.dumps(
            {
                "filename": "sample_complaints.csv",
                "file_size": len(csv_bytes),
                "content_type": "text/csv",
            }
        ).encode(),
        "application/json",
    )
    upload_id = init["upload_id"]
    session_id = init["session_id"]
    print("upload_id", upload_id)
    print("session_id", session_id)

    req("PUT", f"/uploads/{upload_id}/chunk/1", csv_bytes)
    complete = req("POST", f"/uploads/{upload_id}/complete")
    print("upload complete:", complete)
    if complete.get("job_id"):
        print("FAIL: upload should not auto-start a job")
        return 1

    session = req("GET", f"/sessions/{session_id}")
    print("session after upload:", session.get("upload_status"))
    if session.get("upload_status") != "uploaded":
        print("FAIL: expected upload_status=uploaded")
        return 1

    t0 = time.time()
    chunk = req(
        "POST",
        f"/sessions/{session_id}/chunk",
        json.dumps({"chunking_method": "sentence", "chunking_config": {"max_chunk_chars": 2000}}).encode(),
        "application/json",
    )
    job_id = chunk["job_id"]
    print("chunk job", job_id)
    job = poll_job(job_id, timeout_s=30)
    elapsed = time.time() - t0
    print(f"chunking finished in {elapsed:.2f}s -> {job.get('status')}")
    if job.get("status") != "completed":
        print("FAIL chunk job:", job)
        return 1

    preview = req("GET", f"/sessions/{session_id}/chunks")
    print("preview total=", preview.get("total"), "method=", preview.get("method"))
    if not preview.get("total"):
        print("FAIL: no chunks in preview")
        return 1

    t1 = time.time()
    embed = req("POST", f"/sessions/{session_id}/embed")
    embed_job = poll_job(embed["job_id"], timeout_s=90)
    print(f"embedding finished in {time.time() - t1:.2f}s -> {embed_job.get('status')}")
    if embed_job.get("status") != "completed":
        print("FAIL embed job:", embed_job)
        return 1

    session = req("GET", f"/sessions/{session_id}")
    print("final session status:", session.get("upload_status"), "chunks:", session.get("chunk_count"))
    if session.get("upload_status") != "ingested":
        print("FAIL: expected ingested")
        return 1

    print("E2E PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
