import asyncio
import uuid
from pathlib import Path

from api.core.config import settings

_multipart_meta: dict[str, dict] = {}


def _root() -> Path:
    root = Path(settings.local_data_dir) / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key_path(key: str) -> Path:
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def ensure_bucket() -> None:
    _root().mkdir(parents=True, exist_ok=True)


async def create_multipart_upload(key: str, content_type: str) -> str:
    upload_id = str(uuid.uuid4())
    _multipart_meta[upload_id] = {"key": key, "content_type": content_type, "parts": {}}
    staging = _root() / ".multipart" / upload_id
    staging.mkdir(parents=True, exist_ok=True)
    return upload_id


async def upload_part(key: str, upload_id: str, part_number: int, data: bytes) -> str:
    staging = _root() / ".multipart" / upload_id / str(part_number)
    await asyncio.to_thread(staging.write_bytes, data)
    meta = _multipart_meta.setdefault(upload_id, {"key": key, "parts": {}})
    meta["parts"][part_number] = str(staging)
    return f"etag-{part_number}"


async def complete_multipart_upload(
    key: str, upload_id: str, parts: list[dict[str, str | int]]
) -> None:
    dest = _key_path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("wb") as outfile:
        for part in sorted(parts, key=lambda p: p["PartNumber"]):
            chunk_path = _root() / ".multipart" / upload_id / str(part["PartNumber"])
            outfile.write(chunk_path.read_bytes())

    staging = _root() / ".multipart" / upload_id
    if staging.exists():
        for child in staging.iterdir():
            child.unlink(missing_ok=True)
        staging.rmdir()
    _multipart_meta.pop(upload_id, None)


async def download_bytes(key: str) -> bytes:
    path = _key_path(key)
    return await asyncio.to_thread(path.read_bytes)


async def check_blob_store() -> bool:
    try:
        await ensure_bucket()
        return True
    except Exception:
        return False
