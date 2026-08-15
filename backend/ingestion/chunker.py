import re
from typing import Callable

MAX_CHUNK_CHARS = 2000


def _split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
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
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for sentence in sentences:
                    test = f"{buf} {sentence}".strip()
                    if len(test) <= max_chars:
                        buf = test
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = sentence
                if buf:
                    current = buf
                else:
                    current = ""
            else:
                current = para

    if current:
        chunks.append(current)
    return chunks


def semantic_chunk_text(text: str, embed_fn: Callable[[list[str]], list[list[float]]] | None = None) -> list[str]:
    """Semantic chunking with fallback to paragraph/sentence splitting.

    Uses embedding-based breakpoints when embed_fn is provided; otherwise
    uses a deterministic size-aware splitter suitable for tests and fast dev.
    """
    text = text.strip()
    if not text:
        return []

    if embed_fn is None or len(text) < 400:
        return _split_long_text(text)

    try:
        from langchain_experimental.text_splitter import SemanticChunker
        from langchain_core.embeddings import Embeddings

        class _FnEmbeddings(Embeddings):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return embed_fn(texts)

            def embed_query(self, text: str) -> list[float]:
                return embed_fn([text])[0]

        splitter = SemanticChunker(_FnEmbeddings(), breakpoint_threshold_type="percentile")
        docs = splitter.create_documents([text])
        chunks = [d.page_content.strip() for d in docs if d.page_content.strip()]
        final: list[str] = []
        for chunk in chunks:
            final.extend(_split_long_text(chunk))
        return final
    except Exception:
        return _split_long_text(text)
