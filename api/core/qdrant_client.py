from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from api.core.config import settings

_client: AsyncQdrantClient | None = None
VECTOR_SIZE = 384


async def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        if settings.qdrant_mode == "local":
            _client = AsyncQdrantClient(path=settings.qdrant_local_path)
        else:
            _client = AsyncQdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
            )
    return _client


async def close_qdrant() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def ensure_collection() -> None:
    client = await get_qdrant()
    collections = await client.get_collections()
    names = {c.name for c in collections.collections}
    if settings.qdrant_collection not in names:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
        )


async def check_qdrant() -> bool:
    try:
        client = await get_qdrant()
        await client.get_collections()
        return True
    except Exception:
        return False
