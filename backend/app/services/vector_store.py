from __future__ import annotations

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


def _build_sparse_index():
    from app.services.sparse_vector_service import SparseVectorIndex

    ensure_collection()  # tolerate a not-yet-seeded DB
    client = get_client()
    all_points, _next_page = client.scroll(
        collection_name=settings.qdrant_collection,
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )
    documents = [
        {
            "text": point.payload.get("text", "") if point.payload else "",
            "source": point.payload.get("source", "") if point.payload else "",
            "id": str(point.id),
        }
        for point in all_points
    ]
    sparse_index = SparseVectorIndex()
    sparse_index.fit(documents)
    return sparse_index


def sparse_search(query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
    """Pure sparse search using TF-IDF (no dense embeddings, no fusion)."""
    sparse_index = _build_sparse_index()
    return sparse_index.search(query_text, top_k=top_k)


def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    rrf_k: int = 60,
    sparse_top_k: int = 20,
) -> list[RetrievedChunk]:

    from app.services.sparse_vector_service import fuse_rrf

    dense_results = search(query_embedding, top_k=sparse_top_k)
    sparse_index = _build_sparse_index()
    sparse_results = sparse_index.search(query_text, top_k=sparse_top_k)
    fused = fuse_rrf([dense_results, sparse_results], rrf_k=rrf_k)
    return fused[:top_k]
