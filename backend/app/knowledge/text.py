"""Extract text from uploads and split it into overlapping chunks."""

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rst"}
SUPPORTED = TEXT_TYPES | {".pdf"}


class ExtractionError(ValueError):
    """User-safe reason a file cannot be ingested."""


@dataclass(frozen=True)
class Chunk:
    ord: int
    text: str
    page: int | None = None


def extract_text(filename: str, data: bytes) -> tuple[str, list[tuple[int, str]] | None]:
    """Return (full text, optional [(page_number, text)]) for a supported file."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in SUPPORTED:
        raise ExtractionError(
            f"Unsupported file type '{ext or filename}'. Supported: {', '.join(sorted(SUPPORTED))}"
        )
    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractionError("Encrypted PDFs are not supported")
            pages = [
                (i + 1, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages)
            ]
        except PdfReadError as e:
            raise ExtractionError("The PDF could not be read") from e
        text = "\n\n".join(t for _, t in pages if t)
        if not text.strip():
            raise ExtractionError("No extractable text in this PDF (scanned image?)")
        return text, pages
    if b"\x00" in data[:8192]:
        raise ExtractionError("This looks like a binary file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = text.replace("\r\n", "\n").lstrip("﻿")
    if not text.strip():
        raise ExtractionError("The file is empty")
    return text, None


def _split_long(paragraph: str, size: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    parts: list[str] = []
    buf = ""
    for s in sentences:
        while len(s) > size:  # a single huge "sentence": hard wrap
            parts.append(s[:size])
            s = s[size:]
        if len(buf) + len(s) + 1 > size and buf:
            parts.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        parts.append(buf)
    return parts


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[Chunk]:
    """Paragraph-aware chunks of at most `size` characters; consecutive chunks share up to
    `overlap` trailing characters so facts spanning a boundary stay retrievable."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paragraphs:
        pieces.extend(_split_long(p, size) if len(p) > size else [p])
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 2 > size:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n\n{piece}".strip() if tail else piece
            if len(buf) > size:
                buf = piece
        else:
            buf = f"{buf}\n\n{piece}".strip()
    if buf:
        chunks.append(buf)
    return [Chunk(ord=i, text=c) for i, c in enumerate(chunks)]


def chunk_pages(pages: list[tuple[int, str]], size: int, overlap: int) -> list[Chunk]:
    """Chunk page by page so citations can point at a page."""
    out: list[Chunk] = []
    for page_no, text in pages:
        for c in chunk_text(text, size, overlap):
            out.append(Chunk(ord=len(out), text=c.text, page=page_no))
    return out
