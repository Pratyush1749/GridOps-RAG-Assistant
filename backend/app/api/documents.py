"""
Enterprise RAG — Document management endpoints.

Routes (mounted at /api/v1):
  POST   /documents/upload       — upload & index a PDF document
  GET    /documents/             — list all indexed documents
  DELETE /documents/{doc_id}     — remove a document from the index
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.middleware.auth import User, get_current_user
from app.models import RetrievedChunk
from app.services.document_processor import DocumentProcessor
from app.services.embedding_service import embed_texts
from app.services.vector_store import ensure_collection, get_client, upsert_chunks

router = APIRouter(prefix="/documents", tags=["Documents"])

# Lazy-init the processor (avoids Docling loading at import time)
_processor: DocumentProcessor | None = None


def _get_processor() -> DocumentProcessor:
    global _processor
    if _processor is None:
        _processor = DocumentProcessor()
    return _processor


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    chunks_indexed: int
    page_count: int | None = None
    message: str = "Document indexed successfully"


class DocumentListItem(BaseModel):
    doc_id: str
    source: str
    chunk_count: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and index a PDF document",
    description=(
        "Accepts a PDF file, parses it with Docling, generates embeddings, "
        "and upserts all chunks into Qdrant. "
        "**Note:** First upload may take 1–3 minutes while Docling downloads OCR models."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="PDF file to index"),
    user: User = Depends(get_current_user),
) -> UploadResponse:
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are supported",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    doc_id = hashlib.sha256(content).hexdigest()[:16]
    filename = file.filename or "document.pdf"

    logger.info("Indexing document '{}' (doc_id={}) for user={}", filename, doc_id, user.username)

    # Write to temp file for Docling
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        processor = _get_processor()
        raw_chunks = processor.process_document(tmp_path)
    except Exception as exc:
        logger.error("Document processing failed for '{}': {}", filename, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {exc}",
        ) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not raw_chunks:
        raise HTTPException(status_code=400, detail="No text could be extracted from the document")

    # Override source to use the original filename
    chunks = [
        RetrievedChunk(text=c["text"], source=f"{filename}#{doc_id}", score=0.0) for c in raw_chunks
    ]

    try:
        embeddings = embed_texts([c.text for c in chunks])
        ensure_collection()
        upsert_chunks(chunks, embeddings)
    except Exception as exc:
        logger.error("Embedding/upsert failed for '{}': {}", filename, exc)
        raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}") from exc

    page_count = max(
        (c.get("page_number", 0) for c in raw_chunks if "page_number" in c),
        default=None,
    )

    logger.success("Indexed {} chunks from '{}' (doc_id={})", len(chunks), filename, doc_id)
    return UploadResponse(
        doc_id=doc_id,
        filename=filename,
        chunks_indexed=len(chunks),
        page_count=page_count,
    )


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List all indexed documents",
)
async def list_documents(
    user: User = Depends(get_current_user),
) -> DocumentListResponse:
    """
    Scroll the Qdrant collection and return a deduplicated list of
    documents (grouped by source filename).
    """
    try:
        client = get_client()
        all_points, _ = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=10_000,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vector store unavailable: {exc}") from exc

    # Group by source
    source_counts: dict[str, int] = {}
    for point in all_points:
        src = (point.payload or {}).get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    docs = [
        DocumentListItem(
            doc_id=src.split("#")[-1] if "#" in src else src, source=src, chunk_count=count
        )
        for src, count in sorted(source_counts.items())
    ]
    return DocumentListResponse(documents=docs, total=len(docs))


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove a document from the index",
)
async def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Delete all Qdrant points whose `source` field ends with `#<doc_id>`.
    Requires authentication; admin not required (users can delete their own uploads).
    """
    try:
        client = get_client()
        # Scroll to find points matching this doc_id suffix
        all_points, _ = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=10_000,
            with_payload=True,
            with_vectors=False,
        )
        point_ids = [
            p.id for p in all_points if (p.payload or {}).get("source", "").endswith(f"#{doc_id}")
        ]
        if not point_ids:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=point_ids,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc

    return {"status": "ok", "deleted_chunks": len(point_ids), "doc_id": doc_id}
