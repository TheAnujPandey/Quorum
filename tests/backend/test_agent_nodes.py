"""Tests for backend.agent.nodes — mocked LLM calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.nodes import _format_documents


class TestFormatDocuments:
    def test_formats_chunks(self):
        chunks = [
            {"source_ref": "row:1", "chunk_text": "First chunk"},
            {"source_ref": "page:3", "chunk_text": "Second chunk"},
        ]
        result = _format_documents(chunks)
        assert "[row:1]" in result
        assert "First chunk" in result
        assert "[page:3]" in result
        assert "---" in result

    def test_empty_chunks(self):
        assert _format_documents([]) == ""

    def test_missing_fields(self):
        chunks = [{"other": "data"}]
        result = _format_documents(chunks)
        assert "[unknown]" in result


def _assert_message_list(call_args):
    """Verify ainvoke received a [SystemMessage, HumanMessage] list."""
    messages = call_args[0][0]
    assert isinstance(messages, list), f"Expected list, got {type(messages)}"
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)


class TestGradeDocuments:
    @pytest.mark.asyncio
    async def test_grade_sufficient(self):
        mock_response = MagicMock()
        mock_response.content = '{"sufficient": true, "reasoning": "enough context"}'

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import grade_documents
            result = await grade_documents("What happened?", [{"source_ref": "row:1", "chunk_text": "Data"}])
            assert result["sufficient"] is True
            _assert_message_list(mock_llm.ainvoke.call_args)

    @pytest.mark.asyncio
    async def test_grade_insufficient(self):
        mock_response = MagicMock()
        mock_response.content = '{"sufficient": false, "reasoning": "not enough info"}'

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import grade_documents
            result = await grade_documents("What happened?", [])
            assert result["sufficient"] is False

    @pytest.mark.asyncio
    async def test_grade_parse_failure_fallback(self):
        mock_response = MagicMock()
        mock_response.content = "I cannot determine sufficiency."

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import grade_documents
            result = await grade_documents("Q?", [{"source_ref": "r:1", "chunk_text": "data"}])
            assert "sufficient" in result


class TestRewriteQuery:
    @pytest.mark.asyncio
    async def test_rewrite(self):
        mock_response = MagicMock()
        mock_response.content = "What were the deployment issues with Widget A?"

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import rewrite_query
            result = await rewrite_query("Widget A problems", [])
            assert "Widget A" in result
            _assert_message_list(mock_llm.ainvoke.call_args)


class TestGenerateAnswer:
    @pytest.mark.asyncio
    async def test_generate(self):
        mock_response = MagicMock()
        mock_response.content = "According to [row:1], the device failed. [row:1]"

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import generate_answer
            result = await generate_answer("What happened?", [{"source_ref": "row:1", "chunk_text": "Device failed"}])
            assert "[row:1]" in result
            _assert_message_list(mock_llm.ainvoke.call_args)


class TestSelfCheck:
    @pytest.mark.asyncio
    async def test_self_check_high(self):
        mock_response = MagicMock()
        mock_response.content = '{"faithfulness": 0.95, "answer_relevancy": 0.9, "label": "high"}'

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import self_check
            result = await self_check("Q?", [{"source_ref": "r:1", "chunk_text": "data"}], "Answer")
            assert result["label"] == "high"
            assert result["faithfulness"] == 0.95
            _assert_message_list(mock_llm.ainvoke.call_args)

    @pytest.mark.asyncio
    async def test_self_check_parse_failure(self):
        mock_response = MagicMock()
        mock_response.content = "Unable to score."

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.agent.nodes._get_llm", return_value=mock_llm):
            from backend.agent.nodes import self_check
            result = await self_check("Q?", [], "Answer")
            assert result["label"] == "medium"
            assert result["faithfulness"] == 0.5
