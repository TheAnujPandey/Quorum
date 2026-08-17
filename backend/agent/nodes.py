import json
import re
from typing import Any

from langchain_openai import ChatOpenAI
from qdrant_client.http import models as qmodels

from api.core.config import settings
from api.core.qdrant_client import get_qdrant
from backend.agent.llm_context import llm_overrides
from backend.embeddings.model import embed_texts_async
from backend.reranker.model import rerank_pairs_async

RETRIEVAL_TOP_K = 20
RERANK_TOP_K = 3
MAX_RETRIES = 2


async def retrieve_chunks(session_id: str, question: str, limit: int = RETRIEVAL_TOP_K) -> list[dict[str, Any]]:
    vector = (await embed_texts_async([question]))[0]
    client = await get_qdrant()

    response = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="session_id",
                    match=qmodels.MatchValue(value=session_id),
                )
            ]
        ),
        limit=limit,
        with_payload=True,
    )

    chunks: list[dict[str, Any]] = []
    for point in response.points:
        payload = point.payload or {}
        chunks.append(
            {
                "id": str(point.id),
                "score": float(point.score or 0.0),
                "source_ref": payload.get("source_ref", ""),
                "chunk_text": payload.get("chunk_text", ""),
                "payload": payload,
            }
        )
    return chunks


async def rerank_chunks(question: str, chunks: list[dict[str, Any]], top_k: int = RERANK_TOP_K) -> list[dict[str, Any]]:
    if not chunks:
        return []
    texts = [c["chunk_text"] for c in chunks]
    ranked = await rerank_pairs_async(question, texts)
    selected = []
    for idx, score in ranked[:top_k]:
        item = dict(chunks[idx])
        item["rerank_score"] = score
        selected.append(item)
    return selected


def _format_documents(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            f"[{chunk.get('source_ref', 'unknown')}]\n{chunk.get('chunk_text', '')}"
        )
    return "\n\n---\n\n".join(parts)


def _get_llm() -> ChatOpenAI:
    overrides = llm_overrides.get()
    api_key = overrides.get("api_key") or settings.openai_api_key
    model = overrides.get("model") or settings.openai_model
    return ChatOpenAI(
        api_key=api_key,
        model=model,
        temperature=0,
    )


async def grade_documents(question: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.agent.prompts import GRADE_DOCUMENTS

    llm = _get_llm()
    messages = GRADE_DOCUMENTS.format_messages(question=question, documents=_format_documents(chunks))
    response = await llm.ainvoke(messages)
    text = str(response.content)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"sufficient": len(chunks) > 0, "reasoning": "fallback"}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"sufficient": len(chunks) > 0, "reasoning": "parse_error"}


async def rewrite_query(question: str, chunks: list[dict[str, Any]]) -> str:
    from backend.agent.prompts import REWRITE_QUERY

    llm = _get_llm()
    messages = REWRITE_QUERY.format_messages(question=question, documents=_format_documents(chunks))
    response = await llm.ainvoke(messages)
    return str(response.content).strip()


async def generate_answer(question: str, chunks: list[dict[str, Any]]) -> str:
    from backend.agent.prompts import GENERATE_ANSWER

    llm = _get_llm()
    messages = GENERATE_ANSWER.format_messages(question=question, documents=_format_documents(chunks))
    response = await llm.ainvoke(messages)
    return str(response.content).strip()


async def self_check(question: str, chunks: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    from backend.agent.prompts import SELF_CHECK

    llm = _get_llm()
    messages = SELF_CHECK.format_messages(
        question=question,
        documents=_format_documents(chunks),
        answer=answer,
    )
    response = await llm.ainvoke(messages)
    text = str(response.content)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"faithfulness": 0.5, "answer_relevancy": 0.5, "label": "medium"}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"faithfulness": 0.5, "answer_relevancy": 0.5, "label": "medium"}
