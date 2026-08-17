import re as _re
from collections.abc import Callable
from typing import Any

from backend.ingestion.chunker import MAX_CHUNK_CHARS, _split_long_text, semantic_chunk_text

DEFAULT_CHUNKING_METHOD = "sentence"

SUPPORTED_METHODS = ("sentence", "fixed", "recursive", "semantic", "line", "paragraph")


def chunk_text(
    text: str,
    method: str = DEFAULT_CHUNKING_METHOD,
    config: dict[str, Any] | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[str]:
    text = text.strip()
    if not text:
        return []

    cfg = config or {}
    method = method if method in SUPPORTED_METHODS else DEFAULT_CHUNKING_METHOD
    max_chars = int(cfg.get("max_chunk_chars", MAX_CHUNK_CHARS))
    chunk_size = int(cfg.get("chunk_size", 1000))
    chunk_overlap = int(cfg.get("chunk_overlap", 100))

    if method == "line":
        return _chunk_by_line(text, max_chars)

    if method == "paragraph":
        return _chunk_by_paragraph(text, max_chars)

    if method == "sentence":
        return _split_long_text(text, max_chars=max_chars)

    if method == "fixed":
        from langchain_text_splitters import CharacterTextSplitter

        splitter = CharacterTextSplitter(
            separator="\n",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return [c.strip() for c in splitter.split_text(text) if c.strip()]

    if method == "recursive":
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return [c.strip() for c in splitter.split_text(text) if c.strip()]

    if method == "semantic":
        threshold = cfg.get("breakpoint_threshold_type", "percentile")
        return _semantic_with_threshold(text, embed_fn, threshold, max_chars)

    return _split_long_text(text, max_chars=max_chars)


def _chunk_by_line(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Group consecutive non-blank lines into chunks up to max_chars."""
    lines = text.split("\n")
    chunks: list[str] = []
    current = ""
    for line in lines:
        line = line.rstrip()
        candidate = f"{current}\n{line}".strip() if current else line.strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = line.strip()[:max_chars]
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _chunk_by_paragraph(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on double-newlines (paragraphs), merge small ones up to max_chars."""
    paragraphs = _re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(para) > max_chars:
                chunks.extend(_split_long_text(para, max_chars=max_chars))
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _semantic_with_threshold(
    text: str,
    embed_fn: Callable[[list[str]], list[list[float]]] | None,
    threshold_type: str,
    max_chars: int,
) -> list[str]:
    if embed_fn is None or len(text) < 400:
        return _split_long_text(text, max_chars=max_chars)

    try:
        from langchain_core.embeddings import Embeddings
        from langchain_experimental.text_splitter import SemanticChunker

        class _FnEmbeddings(Embeddings):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return embed_fn(texts)

            def embed_query(self, query: str) -> list[float]:
                return embed_fn([query])[0]

        splitter = SemanticChunker(
            _FnEmbeddings(),
            breakpoint_threshold_type=threshold_type,
        )
        docs = splitter.create_documents([text])
        chunks = [d.page_content.strip() for d in docs if d.page_content.strip()]
        final: list[str] = []
        for chunk in chunks:
            final.extend(_split_long_text(chunk, max_chars=max_chars))
        return final
    except Exception:
        return semantic_chunk_text(text, embed_fn=embed_fn)
