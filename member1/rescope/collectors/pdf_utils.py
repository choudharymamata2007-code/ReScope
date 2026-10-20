"""PDF helpers (Tasks 1.3/1.4): page-level text and tables with locators like 'p.12' and
'p.12 table 2', so every number can point back to a place in a document."""
from __future__ import annotations
import io
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PageContent:
    page: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)


def extract_pdf(content: bytes, max_pages: Optional[int] = None) -> list[PageContent]:
    import pdfplumber
    pages: list[PageContent] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                if max_pages and i > max_pages:
                    break
                try:
                    text = page.extract_text() or ""
                    tables = [[[("" if c is None else str(c)).strip() for c in row] for row in t]
                              for t in (page.extract_tables() or [])]
                except Exception:
                    text, tables = "", []
                pages.append(PageContent(i, text, tables))
    except Exception:
        pass
    return pages


def chunk_text(text: str, max_chars: int = 1800) -> list[str]:
    """Split page text on paragraph boundaries into chunks under max_chars."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()] or [text.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 > max_chars and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


def is_pdf(content: bytes, content_type: str = "", url: str = "") -> bool:
    return content[:5] == b"%PDF-" or "pdf" in content_type.lower() or url.lower().split("?")[0].endswith(".pdf")
