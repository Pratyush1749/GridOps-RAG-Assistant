from __future__ import annotations

import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.models import RetrievedChunk

VECTOR_SIZE = 1536

# Fixed namespace for deriving deterministic point IDs from (source, text).
# Any constant UUID works here — it just needs to stay stable across runs so
# uuid5(...) is reproducible for the same chunk.
_POINT_ID_NAMESPACE = uuid.UUID("f2a1b9d4-6e3c-4a8b-9d2e-7c5f1a3b8e6d")


def _point_id(source: str, text: str) -> str:
    """Deterministic point ID for a chunk, derived from its (source, text).

    Using a random UUID per upsert (the old behavior) means re-running
    ingestion for the same document creates a brand-new point every time
    instead of replacing the existing one, silently duplicating the
    collection. Deriving the ID from content makes upserts idempotent: the
    same chunk always maps to the same point, so Qdrant overwrites it in
    place on re-ingestion.
    """
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{source}::{text}"))


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=30)


def ensure_collection() -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}

    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def upsert_chunks(chunks: list[RetrievedChunk], embeddings: list[list[float]]) -> None:
    ensure_collection()
    client = get_client()
    points = [
        PointStruct(
            id=_point_id(chunk.source, chunk.text),
            vector=embedding,
            payload={"text": chunk.text, "source": chunk.source},
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    client.upsert(collection_name=settings.qdrant_collection, points=points)
    invalidate_sparse_index()


def search(query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
    ensure_collection()  # tolerate a not-yet-seeded DB: query an empty collection, don't 404
    client = get_client()
    results = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_embedding,
        limit=top_k,
        with_payload=True,
    ).points

    return [
        RetrievedChunk(
            text=(p.payload or {}).get("text", ""),
            source=(p.payload or {}).get("source", ""),
            score=float(p.score),
        )
        for p in results
    ]


# ---------------------------------------------------------------------------
# Sparse (BM25) index: built once and reused until the collection changes.
# Previously a fresh TF-IDF index was fitted on every sparse/hybrid query by
# scrolling the whole collection - O(corpus) work per request.
# ---------------------------------------------------------------------------

_sparse_lock = threading.Lock()
_sparse_cache: dict = {"index": None, "point_count": None}


def invalidate_sparse_index() -> None:
    """Drop the cached BM25 index (call after upserting or deleting points)."""
    with _sparse_lock:
        _sparse_cache["index"] = None
        _sparse_cache["point_count"] = None


def _scroll_all_payloads(client: QdrantClient) -> list[dict]:
    """Read every point's payload, following scroll pagination."""
    documents: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            documents.append(
                {
                    "text": payload.get("text", ""),
                    "source": payload.get("source", ""),
                    "id": str(point.id),
                }
            )
        if offset is None:
            return documents


def _build_sparse_index():
    from app.services.sparse_vector_service import BM25Index

    ensure_collection()  # tolerate a not-yet-seeded DB
    client = get_client()
    point_count = client.count(collection_name=settings.qdrant_collection, exact=True).count

    with _sparse_lock:
        cached = _sparse_cache["index"]
        if cached is not None and _sparse_cache["point_count"] == point_count:
            return cached

    sparse_index = BM25Index()
    sparse_index.fit(_scroll_all_payloads(client))

    with _sparse_lock:
        _sparse_cache["index"] = sparse_index
        _sparse_cache["point_count"] = point_count
    return sparse_index


def sparse_search(query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
    """Pure sparse search using BM25 (no dense embeddings, no fusion)."""
    sparse_index = _build_sparse_index()
    return sparse_index.search(query_text, top_k=top_k)


def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    rrf_k: int | None = None,
    candidates_per_retriever: int = 20,
) -> list[RetrievedChunk]:
    """Dense top-N + BM25 top-N, fused with Reciprocal Rank Fusion."""
    from app.services.sparse_vector_service import fuse_rrf

    if rrf_k is None:
        rrf_k = settings.rrf_k
    dense_results = search(query_embedding, top_k=candidates_per_retriever)
    sparse_index = _build_sparse_index()
    sparse_results = sparse_index.search(query_text, top_k=candidates_per_retriever)
    fused = fuse_rrf([dense_results, sparse_results], rrf_k=rrf_k)
    return fused[:top_k]
