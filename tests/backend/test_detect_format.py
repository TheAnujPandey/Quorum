"""Tests for backend.ingestion.detect_format."""

from backend.ingestion.detect_format import detect_format_from_filename


class TestDetectFormat:
    def test_csv(self):
        assert detect_format_from_filename("data.csv") == "csv"
        assert detect_format_from_filename("DATA.CSV") == "csv"

    def test_xlsx(self):
        assert detect_format_from_filename("report.xlsx") == "xlsx"

    def test_xls(self):
        assert detect_format_from_filename("old.xls") == "xlsx"

    def test_pdf(self):
        assert detect_format_from_filename("document.pdf") == "pdf"

    def test_txt(self):
        assert detect_format_from_filename("notes.txt") == "txt"

    def test_unknown(self):
        assert detect_format_from_filename("image.png") == "unknown"
        assert detect_format_from_filename("noext") == "unknown"

    def test_case_insensitive(self):
        assert detect_format_from_filename("file.PDF") == "pdf"
        assert detect_format_from_filename("file.TXT") == "txt"
