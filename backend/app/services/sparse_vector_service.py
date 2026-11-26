"""Sparse (lexical) retrieval with Okapi BM25, plus Reciprocal Rank Fusion.

BM25 score of chunk d for query q:

    sum over query terms t of
        IDF(t) * f(t,d) * (k1 + 1) / ( f(t,d) + k1 * (1 - b + b * |d| / avgdl) )

    IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

* f(t,d)   term frequency of t in d
* |d|      length of d in tokens; avgdl = mean length over the corpus
* k1       term-frequency saturation (1.2-2.0 typical): the 10th mention of a
           word adds far less than the 1st
* b        length normalisation (0.75 typical): long chunks that mention
           everything a little are penalised

This replaces the earlier TF-IDF + cosine index, which had neither
saturation nor a tunable length penalty.
"""

import threading
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer

from app.models import RetrievedChunk

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


class BM25Index:
    """In-memory Okapi BM25 index over chunk texts."""

    def __init__(self, k1: float = DEFAULT_K1, b: float = DEFAULT_B) -> None:
        self.k1 = k1
        self.b = b
        # Same tokenisation as before (lowercase, English stop words removed,
        # tokens of 2+ word characters), so "XFMR-00141" -> ["xfmr", "00141"].
        self.vectorizer = CountVectorizer(stop_words="english")
        self.documents: list[dict] = []
        # scipy CSR matrix (n_docs x vocab) of raw term counts once fitted.
        self.term_counts: Any = None
        self.idf: np.ndarray | None = None
        self.doc_len_norm: np.ndarray | None = None  # k1 * (1 - b + b*|d|/avgdl)
        self._lock = threading.RLock()

    def fit(self, documents: list[dict]) -> None:
        with self._lock:
            self.documents = documents
            self.term_counts = None
            self.idf = None
            self.doc_len_norm = None
            if not documents:
                return

            texts = [doc.get("text", "") for doc in documents]
            try:
                counts = self.vectorizer.fit_transform(texts).tocsr()
            except ValueError:  # empty vocabulary (e.g. only stop words)
                return
            if counts.shape[1] == 0:
                return

            n_docs = counts.shape[0]
            doc_freq = np.bincount(counts.indices, minlength=counts.shape[1])
            self.idf = np.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))

            doc_len = np.asarray(counts.sum(axis=1)).ravel().astype(float)
            avgdl = doc_len.mean() if doc_len.mean() > 0 else 1.0
            self.doc_len_norm = self.k1 * (1.0 - self.b + self.b * doc_len / avgdl)
            self.term_counts = counts

    def scores(self, query: str) -> np.ndarray:
        """BM25 score of every indexed chunk for `query` (0 for no overlap)."""
        with self._lock:
            if self.term_counts is None or self.idf is None or self.doc_len_norm is None:
                return np.zeros(len(self.documents))

            vocab = self.vectorizer.vocabulary_
            analyzer = self.vectorizer.build_analyzer()
            # Each distinct query term counts once (standard Okapi BM25).
            term_ids = sorted({vocab[t] for t in analyzer(query) if t in vocab})
            total = np.zeros(self.term_counts.shape[0])
            for tid in term_ids:
                col = self.term_counts.getcol(tid).tocoo()
                tf = col.data.astype(float)
                rows = col.row
                denom = tf + self.doc_len_norm[rows]
                total[rows] += self.idf[tid] * tf * (self.k1 + 1.0) / denom
            return total

    def search(self, query: str, top_k: int = 20) -> list[RetrievedChunk]:
        """Return the top-k chunks by BM25 score, skipping zero-score chunks."""
        with self._lock:
            if not self.documents:
                return []
            scores = self.scores(query)
            top_indices = np.argsort(-scores, kind="stable")[:top_k]

            results: list[RetrievedChunk] = []
            for idx in top_indices:
                score = float(scores[idx])
                if score <= 0:
                    continue
                doc = self.documents[idx]
                results.append(
                    RetrievedChunk(
                        text=doc.get("text", ""),
                        source=doc.get("source", ""),
                        score=score,
                    )
                )
            return results


# Backwards-compatible name: older imports referenced SparseVectorIndex.
SparseVectorIndex = BM25Index


def fuse_rrf(
    result_lists: list[list[RetrievedChunk]],
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion.

    RRF(d) = sum over lists of 1 / (rrf_k + rank), with rank starting at 1.
    Raw scores are ignored, so retrievers on different scales (cosine vs
    BM25) can be combined without normalisation.
    """
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            key = chunk.text
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in meta:
                meta[key] = {"text": chunk.text, "source": chunk.source}

    return [
        RetrievedChunk(text=text, source=meta[text]["source"], score=score)
        for text, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ]
