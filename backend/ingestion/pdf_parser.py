"""PDF parsing: per-page text extraction (pypdf) + table extraction (pdfplumber).

Scanned/image-only PDFs with no extractable text are explicitly unsupported
and will raise ValueError.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field


@dataclass
class PageContent:
    page_number: int
    prose: str
    tables: list[str] = field(default_factory=list)


def _table_to_markdown(table: list[list[str | None]]) -> str:
    if not table or len(table) < 2:
        return ""
    headers = [str(c or "").replace("\x00", "").strip() for c in table[0]]
    rows = table[1:]

    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [str(c or "").replace("\x00", "").strip().replace("|", "\\|") for c in row]
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells[:len(headers)]) + " |")
    return "\n".join(lines)


def parse_pdf(file_bytes: bytes) -> list[PageContent]:
    """Extract text and tables from each page of a PDF.

    Returns a list of PageContent, one per page. Raises ValueError if the PDF
    contains no extractable text at all (scanned/image-only).
    """
    import pdfplumber
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError("PDF has no pages")

    pages: list[PageContent] = []
    total_text_chars = 0

    plumber_pdf = pdfplumber.open(io.BytesIO(file_bytes))

    for page_idx in range(total_pages):
        page_num = page_idx + 1

        pypdf_page = reader.pages[page_idx]
        raw_text = (pypdf_page.extract_text() or "").replace("\x00", "").strip()

        tables_md: list[str] = []
        plumber_page = plumber_pdf.pages[page_idx] if page_idx < len(plumber_pdf.pages) else None
        if plumber_page:
            for tbl in plumber_page.extract_tables() or []:
                md = _table_to_markdown(tbl)
                if md:
                    tables_md.append(md)

        total_text_chars += len(raw_text) + sum(len(t) for t in tables_md)

        if raw_text or tables_md:
            pages.append(PageContent(page_number=page_num, prose=raw_text, tables=tables_md))

    plumber_pdf.close()

    if total_text_chars < 20:
        raise ValueError(
            "PDF appears to be scanned/image-only — no extractable text found. "
            "OCR is not supported in v1."
        )

    return pages
