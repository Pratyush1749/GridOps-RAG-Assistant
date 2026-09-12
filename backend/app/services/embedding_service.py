import logging

from openai import OpenAI

from app.config import settings
from app.services.llm_service import _is_real_key
from app.services.query_cache_service import query_cache

logger = logging.getLogger(__name__)

_EMBED_DIM = 1536  # Qdrant collection is created with this size
_LOCAL_FALLBACK_CACHE_TAG = f"local:all-MiniLM-L6-v2:padded{_EMBED_DIM}"

# Only build the OpenAI client when a real key is configured; otherwise every
# embed call would waste a failing 401 before falling back to the local model.
openai_client: OpenAI | None = (
    OpenAI(api_key=settings.openai_api_key) if _is_real_key(settings.openai_api_key) else None
)
if openai_client is None:
    logger.info("OPENAI_API_KEY not set/placeholder — embeddings use local all-MiniLM-L6-v2")

_local_model = None  # lazy singleton — loaded once, not per call


def _get_local_model():
    """Load the local SentenceTransformers model once and reuse it."""
    global _local_model
    if _local_model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _local_model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
    return _local_model


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Local embeddings, zero-padded to _EMBED_DIM so Qdrant accepts them."""
    raw = _get_local_model().encode(texts)
    out: list[list[float]] = []
    for emb in raw:
        vec = list(emb.tolist())
        if len(vec) < _EMBED_DIM:
            vec = vec + [0.0] * (_EMBED_DIM - len(vec))
        elif len(vec) > _EMBED_DIM:
            vec = vec[:_EMBED_DIM]
        out.append(vec)
    return out


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    if model is None:
        model = settings.embedding_model

    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []
    for i, text in enumerate(texts):
        # Look up under the *requested* model's namespace only — if this text
        # was previously cached under the local-fallback tag (e.g. because
        # OpenAI was unreachable at the time), that entry is deliberately a
        # miss here so we retry OpenAI now that it may be working again.
        cached = query_cache.get_embedding(text, model)
        if cached is not None:
            results[i] = cached
        else:
            miss_indices.append(i)
            miss_texts.append(text)

    if not miss_texts:
        return [r for r in results if r is not None]

    vectors: list[list[float]] | None = None
    cache_model_tag = model
    if openai_client is not None:
        try:
            response = openai_client.embeddings.create(input=miss_texts, model=model)
            vectors = [item.embedding for item in response.data]
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenAI embedding failed (%s); using local model", e)

    if vectors is None:
        vectors = _embed_local(miss_texts)
        # Tag these as local-fallback vectors, distinct from `model`, so a
        # later request (once OpenAI is reachable again) misses this cache
        # entry and recomputes a real embedding instead of reusing a padded
        # local vector indefinitely.
        cache_model_tag = _LOCAL_FALLBACK_CACHE_TAG

    for idx_in_misses, vector in enumerate(vectors):
        original_idx = miss_indices[idx_in_misses]
        results[original_idx] = vector
        query_cache.set_embedding(miss_texts[idx_in_misses], vector, cache_model_tag)

    return [r for r in results if r is not None]
