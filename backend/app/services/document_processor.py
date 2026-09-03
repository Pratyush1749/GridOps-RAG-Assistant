"""Document parsing + chunking.

PDFs go through pypdf (text layer only) — fast and memory-safe. Docling
rasterises every page for its layout/OCR models, which OOMs (`std::bad_alloc`)
on modest machines. Everything else (DOCX / HTML / MD / TXT) still uses Docling.

Env overrides:
  PDF_BACKEND=docling   -> force Docling for PDFs too (needs plenty of RAM)
  DOCLING_OCR=1         -> enable OCR in the Docling path
  DOCLING_TABLES=1      -> enable table-structure model in the Docling path
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from loguru import logger

# pypdf is chatty about recoverable xref quirks in otherwise-fine PDFs.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def _split_text(text: str, max_chars: int = 1500, overlap: int = 150) -> list[str]:
    """Sliding-window split, preferring a sentence/space break in the 2nd half
    of each window so `start` always advances by at least ~max_chars/2."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text] if text else []
    out: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            floor = start + max_chars // 2  # never break before the midpoint
            brk = text.rfind(". ", floor, end)
            if brk == -1:
                brk = text.rfind(" ", floor, end)
            if brk != -1:
                end = brk + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - overlap, floor)
    return out


class DocumentProcessor:
    def __init__(self) -> None:
        self._docling: tuple | None = None  # lazily built (only for non-PDF formats)

    # -- Docling (DOCX / HTML / MD / TXT) -----------------------------------
    def _get_docling(self) -> tuple:
        if self._docling is None:
            from docling.chunking import HybridChunker
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            opts = PdfPipelineOptions()
            opts.accelerator_options = AcceleratorOptions(num_threads=8)
            opts.do_ocr = os.getenv("DOCLING_OCR", "0") == "1"
            opts.do_table_structure = os.getenv("DOCLING_TABLES", "0") == "1"
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
            )
            self._docling = (converter, HybridChunker())
        return self._docling

    # -- Public entry point ----------------------------------------------------
    def process_document(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        use_docling_for_pdf = os.getenv("PDF_BACKEND", "pypdf").lower() == "docling"
        if path.suffix.lower() == ".pdf" and not use_docling_for_pdf:
            return self._process_pdf(path)
        return self._process_with_docling(path)

    # -- pypdf path (memory-safe, no ML) -------------------------------------
    def _process_pdf(self, path: Path) -> list[dict]:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        chunks: list[dict] = []
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001 - skip an unreadable page, keep the rest
                continue
            for piece in _split_text(text):
                chunks.append({"text": piece, "source": path.name, "page_number": page_no})
        logger.info("Processed {} chunks from {} (pypdf)", len(chunks), path.name)
        return chunks

    # -- Docling path -------------------------------------------------------
    def _process_with_docling(self, path: Path) -> list[dict]:
        converter, chunker = self._get_docling()
        doc = converter.convert(str(path)).document
        chunks: list[dict] = []
        for chunk in chunker.chunk(doc):
            meta: dict = {"text": chunk.text, "source": path.name}
            if hasattr(chunk, "meta") and hasattr(chunk.meta, "doc_items"):
                items = chunk.meta.doc_items
                if items and hasattr(items[0], "prov") and items[0].prov:
                    meta["page_number"] = items[0].prov[0].page_no
            chunks.append(meta)
        logger.info("Processed {} chunks from {}", len(chunks), path.name)
        return chunks
