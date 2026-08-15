"""Tests for backend.ingestion.chunker."""

from backend.ingestion.chunker import MAX_CHUNK_CHARS, _split_long_text, semantic_chunk_text


class TestSplitLongText:
    def test_short_text_returns_single_chunk(self):
        text = "Hello world"
        result = _split_long_text(text)
        assert result == ["Hello world"]

    def test_empty_text_returns_single_chunk(self):
        result = _split_long_text("")
        assert result == [""]

    def test_respects_max_chars(self):
        text = ("A" * 500 + "\n\n") * 10
        result = _split_long_text(text, max_chars=600)
        for chunk in result:
            assert len(chunk) <= 600

    def test_splits_on_paragraph_boundaries(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = _split_long_text(text, max_chars=30)
        assert len(result) >= 2
        assert all(chunk.strip() for chunk in result)

    def test_handles_long_single_paragraph(self):
        text = "Word. " * 500
        result = _split_long_text(text, max_chars=200)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= MAX_CHUNK_CHARS

    def test_default_max_chars_is_2000(self):
        assert MAX_CHUNK_CHARS == 2000


class TestSemanticChunkText:
    def test_empty_text(self):
        assert semantic_chunk_text("") == []

    def test_whitespace_only(self):
        assert semantic_chunk_text("   ") == []

    def test_short_text_no_embed_fn(self):
        result = semantic_chunk_text("Short text")
        assert result == ["Short text"]

    def test_fallback_without_embed_fn(self):
        text = "A" * 500
        result = semantic_chunk_text(text, embed_fn=None)
        assert len(result) >= 1
        assert all(chunk for chunk in result)

    def test_with_embed_fn_short_text_skips_semantic(self):
        def fake_embed(texts):
            return [[0.0] * 384 for _ in texts]
        result = semantic_chunk_text("Short", embed_fn=fake_embed)
        assert result == ["Short"]
