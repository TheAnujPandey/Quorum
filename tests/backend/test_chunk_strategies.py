"""Tests for backend.ingestion.chunk_strategies."""

from backend.ingestion.chunk_strategies import (
    DEFAULT_CHUNKING_METHOD,
    SUPPORTED_METHODS,
    chunk_text,
)


class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("") == []

    def test_whitespace_text(self):
        assert chunk_text("   ") == []

    def test_default_method_is_sentence(self):
        assert DEFAULT_CHUNKING_METHOD == "sentence"

    def test_supported_methods(self):
        assert "sentence" in SUPPORTED_METHODS
        assert "fixed" in SUPPORTED_METHODS
        assert "recursive" in SUPPORTED_METHODS
        assert "semantic" in SUPPORTED_METHODS

    def test_sentence_method(self):
        text = "Hello world. This is a test."
        result = chunk_text(text, method="sentence")
        assert len(result) >= 1
        assert result[0] == text

    def test_fixed_method(self):
        text = "Line one\nLine two\nLine three\nLine four"
        result = chunk_text(text, method="fixed", config={"chunk_size": 20, "chunk_overlap": 0})
        assert len(result) >= 1

    def test_recursive_method(self):
        text = "Word " * 500
        result = chunk_text(text, method="recursive", config={"chunk_size": 100, "chunk_overlap": 10})
        assert len(result) > 1

    def test_unknown_method_falls_back_to_sentence(self):
        text = "Hello world"
        result = chunk_text(text, method="nonexistent")
        assert result == ["Hello world"]

    def test_semantic_without_embed_fn_falls_back(self):
        text = "A " * 300
        result = chunk_text(text, method="semantic", embed_fn=None)
        assert len(result) >= 1

    def test_max_chunk_chars_config_splits(self):
        text = "First sentence. Second sentence. Third sentence."
        result = chunk_text(text, method="sentence", config={"max_chunk_chars": 30})
        assert len(result) >= 2
