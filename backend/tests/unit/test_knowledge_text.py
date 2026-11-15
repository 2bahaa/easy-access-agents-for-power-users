"""Extraction, chunking and rank fusion (pure functions)."""

import pytest

from app.knowledge.text import ExtractionError, chunk_pages, chunk_text, extract_text
from app.services.knowledge_service import rrf


def _pdf(text: str) -> bytes:
    """A minimal one-page PDF with a text object (no external tools needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_text_and_markdown() -> None:
    text, pages = extract_text("notes.md", "﻿# Title\r\n\r\nBody".encode())
    assert text == "# Title\n\nBody" and pages is None


def test_pdf_pages() -> None:
    text, pages = extract_text("doc.pdf", _pdf("Quarterly revenue grew 12 percent"))
    assert "Quarterly revenue grew 12 percent" in text
    assert pages is not None and pages[0][0] == 1


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("tool.exe", b"MZ", "Unsupported file type"),
        ("blob.txt", b"abc\x00def", "binary"),
        ("empty.txt", b"   \n ", "empty"),
        ("bad.pdf", b"%PDF-1.4 garbage", "PDF"),
    ],
)
def test_rejections(name: str, data: bytes, message: str) -> None:
    with pytest.raises(ExtractionError, match=message):
        extract_text(name, data)


def test_chunking_respects_size_and_overlap() -> None:
    paragraphs = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(20))
    chunks = chunk_text(paragraphs, size=500, overlap=80)
    assert len(chunks) > 3
    assert all(len(c.text) <= 500 for c in chunks)
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    # Consecutive chunks share the overlap tail.
    assert chunks[0].text[-40:] in chunks[1].text


def test_long_sentences_are_hard_wrapped() -> None:
    chunks = chunk_text("x" * 2500, size=400, overlap=0)
    assert all(len(c.text) <= 400 for c in chunks) and "".join(c.text for c in chunks) == "x" * 2500


def test_page_chunks_keep_page_numbers() -> None:
    chunks = chunk_pages([(1, "alpha"), (2, "beta")], 900, 100)
    assert [(c.page, c.text) for c in chunks] == [(1, "alpha"), (2, "beta")]


def test_reciprocal_rank_fusion() -> None:
    scores = rrf([[1, 2, 3], [3, 1]])
    assert max(scores, key=lambda k: scores[k]) == 1  # high in both lists
    assert scores[3] > scores[2]  # appears in both lists
