import asyncio
from functools import lru_cache

from api.core.config import settings

_model = None
_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings.reranker_model_name)


def get_reranker_model():
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def rerank_pairs(query: str, texts: list[str]) -> list[tuple[int, float]]:
    if not texts:
        return []
    model = get_reranker_model()
    pairs = [[query, text] for text in texts]
    scores = model.predict(pairs)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [(idx, float(score)) for idx, score in ranked]


async def rerank_pairs_async(query: str, texts: list[str]) -> list[tuple[int, float]]:
    async with _lock:
        return await asyncio.to_thread(rerank_pairs, query, texts)
