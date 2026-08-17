import asyncio
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from api.core.config import settings
from backend.agent import nodes
from backend.agent.prompts import INSUFFICIENT_RESPONSE

_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.llm_concurrency_limit)
    return _llm_semaphore


class AgentState(TypedDict):
    session_id: str
    question: str
    rewritten_question: str
    chunks: list[dict[str, Any]]
    retries_used: int
    sufficient: bool
    answer: str
    insufficient: bool
    confidence: dict[str, Any]
    citations: list[dict[str, str]]


MAX_RETRIES = 2


async def _retrieve(state: AgentState) -> dict[str, Any]:
    chunks = await nodes.retrieve_chunks(state["session_id"], state["rewritten_question"])
    return {"chunks": chunks}


async def _rerank(state: AgentState) -> dict[str, Any]:
    chunks = await nodes.rerank_chunks(state["rewritten_question"], state["chunks"])
    return {"chunks": chunks}


async def _grade(state: AgentState) -> dict[str, Any]:
    async with _get_semaphore():
        grade = await nodes.grade_documents(state["rewritten_question"], state["chunks"])
    return {"sufficient": bool(grade.get("sufficient"))}


async def _rewrite(state: AgentState) -> dict[str, Any]:
    async with _get_semaphore():
        rewritten = await nodes.rewrite_query(state["question"], state["chunks"])
    return {"rewritten_question": rewritten, "retries_used": state["retries_used"] + 1}


async def _generate(state: AgentState) -> dict[str, Any]:
    async with _get_semaphore():
        answer = await nodes.generate_answer(state["question"], state["chunks"])
    return {"answer": answer}


def _build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    citations = []
    for chunk in chunks[:3]:
        excerpt = chunk.get("chunk_text", "")[:300]
        citations.append({"source_ref": chunk.get("source_ref", ""), "excerpt": excerpt})
    return citations


async def _self_check(state: AgentState) -> dict[str, Any]:
    async with _get_semaphore():
        result = await nodes.self_check(state["question"], state["chunks"], state["answer"])
    return {
        "confidence": {
            "label": result.get("label", "medium"),
            "faithfulness": float(result.get("faithfulness", 0.5)),
            "answer_relevancy": float(result.get("answer_relevancy", 0.5)),
        },
        "citations": _build_citations(state["chunks"]),
    }


async def _respond_insufficient(state: AgentState) -> dict[str, Any]:
    return {
        "answer": INSUFFICIENT_RESPONSE,
        "insufficient": True,
        "citations": _build_citations(state["chunks"]),
    }


def _grade_router(state: AgentState) -> Literal["generate", "rewrite_query", "respond_insufficient"]:
    if state["sufficient"]:
        return "generate"
    if state["retries_used"] < MAX_RETRIES:
        return "rewrite_query"
    return "respond_insufficient"


def _build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("retrieve", _retrieve)
    builder.add_node("rerank", _rerank)
    builder.add_node("grade_documents", _grade)
    builder.add_node("rewrite_query", _rewrite)
    builder.add_node("generate", _generate)
    builder.add_node("self_check", _self_check)
    builder.add_node("respond_insufficient", _respond_insufficient)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "rerank")
    builder.add_edge("rerank", "grade_documents")
    builder.add_conditional_edges(
        "grade_documents",
        _grade_router,
        {
            "generate": "generate",
            "rewrite_query": "rewrite_query",
            "respond_insufficient": "respond_insufficient",
        },
    )
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_edge("generate", "self_check")
    builder.add_edge("self_check", END)
    builder.add_edge("respond_insufficient", END)

    return builder.compile()


_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


async def run_agent(session_id: str, question: str) -> dict[str, Any]:
    """Run the corrective RAG agent. Same external API as before."""
    initial_state: AgentState = {
        "session_id": session_id,
        "question": question,
        "rewritten_question": question,
        "chunks": [],
        "retries_used": 0,
        "sufficient": False,
        "answer": "",
        "insufficient": False,
        "confidence": {"label": "low", "faithfulness": 0.0, "answer_relevancy": 0.0},
        "citations": [],
    }

    graph = _get_graph()
    final_state = await graph.ainvoke(initial_state)

    return {
        "answer": final_state["answer"],
        "citations": final_state["citations"],
        "confidence": final_state["confidence"],
        "retries_used": final_state["retries_used"],
        "insufficient": final_state["insufficient"],
    }
