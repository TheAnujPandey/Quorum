import asyncio
from functools import lru_cache

from api.core.config import settings

_model = None
_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model_name)


def get_embedding_model():
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


async def embed_texts_async(texts: list[str]) -> list[list[float]]:
    async with _lock:
        return await asyncio.to_thread(embed_texts, texts)
