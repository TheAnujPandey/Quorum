"""Tests for backend.ingestion.pdf_parser."""

import io

import pytest

from backend.ingestion.pdf_parser import PageContent, _table_to_markdown, parse_pdf


class TestTableToMarkdown:
    def test_basic_table(self):
        table = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]
        md = _table_to_markdown(table)
        assert "| Name | Age |" in md
        assert "| --- | --- |" in md
        assert "| Alice | 30 |" in md

    def test_empty_table(self):
        assert _table_to_markdown([]) == ""

    def test_single_row_table(self):
        assert _table_to_markdown([["Header"]]) == ""

    def test_none_cells(self):
        table = [["Col"], [None], ["Value"]]
        md = _table_to_markdown(table)
        assert "| Col |" in md
        assert "|  |" in md  # None becomes empty
        assert "| Value |" in md

    def test_pipe_escaping(self):
        table = [["Data"], ["val|ue"]]
        md = _table_to_markdown(table)
        assert "val\\|ue" in md


class TestParsePdf:
    def _make_pdf(self, page_count: int = 1) -> bytes:
        """Create a minimal blank PDF."""
        from pypdf import PdfWriter
        from pypdf._page import PageObject

        writer = PdfWriter()
        for _ in range(page_count):
            page = PageObject.create_blank_page(width=612, height=792)
            writer.add_page(page)

        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def test_empty_pdf_raises(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        buf = io.BytesIO()
        writer.write(buf)
        with pytest.raises(ValueError, match="no pages"):
            parse_pdf(buf.getvalue())

    def test_returns_page_content_type(self):
        pc = PageContent(page_number=1, prose="Hello", tables=["| A |"])
        assert pc.page_number == 1
        assert pc.prose == "Hello"
        assert len(pc.tables) == 1
