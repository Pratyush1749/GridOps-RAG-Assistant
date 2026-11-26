"""Unit tests for BM25, Reciprocal Rank Fusion, SQL policy and the HITL gate.

No database, Qdrant or API keys needed.
"""

from __future__ import annotations

import math

import pytest

from app.models import RetrievedChunk
from app.services.sparse_vector_service import BM25Index, fuse_rrf
from app.services.sql_service import validate_sql

pytestmark = pytest.mark.unit


def _doc(tokens: list[str], source: str) -> dict:
    return {"text": " ".join(tokens), "source": source}


def _filler(n: int, tag: str) -> list[str]:
    return [f"{tag}{i}" for i in range(n)]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


def test_bm25_matches_hand_computed_scores() -> None:
    """Worked example: query 'transformer overtemperature', N=3, avgdl=20."""
    docs = [
        _doc(["transformer"] * 2 + ["overtemperature"] + _filler(7, "a"), "d1"),  # len 10
        _doc(["transformer"] * 4 + _filler(26, "b"), "d2"),  # len 30
        _doc(["transformer", "overtemperature"] + _filler(18, "c"), "d3"),  # len 20
    ]
    index = BM25Index(k1=1.5, b=0.75)
    index.fit(docs)
    scores = index.scores("transformer overtemperature")

    idf_t = math.log(1 + 0.5 / 3.5)
    idf_o = math.log(1 + 1.5 / 2.5)
    expected_d1 = idf_t * 2 * 2.5 / (2 + 1.5 * 0.625) + idf_o * 2.5 / (1 + 1.5 * 0.625)
    expected_d2 = idf_t * 4 * 2.5 / (4 + 1.5 * 1.375)
    expected_d3 = idf_t + idf_o

    assert scores[0] == pytest.approx(expected_d1, rel=1e-9)  # 0.8337
    assert scores[1] == pytest.approx(expected_d2, rel=1e-9)  # 0.2203
    assert scores[2] == pytest.approx(expected_d3, rel=1e-9)  # 0.6035
    assert [c.source for c in index.search("transformer overtemperature")] == ["d1", "d3", "d2"]


def test_bm25_term_frequency_saturates() -> None:
    """Ten mentions are worth far less than ten times one mention."""
    docs = [
        _doc(["breaker"] + _filler(9, "x"), "once"),
        _doc(["breaker"] * 10, "ten"),
        _doc(_filler(10, "y"), "none"),
    ]
    index = BM25Index()
    index.fit(docs)
    once, ten, _ = index.scores("breaker")
    assert ten > once
    assert ten < 3 * once


def test_bm25_finds_exact_asset_tag_among_near_duplicates() -> None:
    template = "Inspection report for transformer {tag}. Oil clear, bushings clean."
    docs = [
        {"text": template.format(tag=f"XFMR-{i:05d}"), "source": f"inspection-{i:04d}.txt"}
        for i in (114, 141, 411, 14)
    ]
    index = BM25Index()
    index.fit(docs)
    top = index.search("Who manufactured transformer XFMR-00141?", top_k=1)
    assert top[0].source == "inspection-0141.txt"


def test_bm25_empty_and_no_overlap() -> None:
    index = BM25Index()
    index.fit([])
    assert index.search("anything") == []
    index.fit([_doc(["feeder", "restoration"], "a")])
    assert index.search("crossword puzzle") == []


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _chunks(names: list[str]) -> list[RetrievedChunk]:
    return [RetrievedChunk(text=n, source=n, score=0.0) for n in names]


def test_rrf_worked_example_k60() -> None:
    dense = _chunks(["A", "B", "C", "D"])
    sparse = _chunks(["E", "C", "A", "F"])
    fused = fuse_rrf([dense, sparse], rrf_k=60)
    assert [c.text for c in fused][:4] == ["A", "C", "E", "B"]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 63)
    assert fused[2].score == pytest.approx(1 / 61)


# ---------------------------------------------------------------------------
# SQL policy
# ---------------------------------------------------------------------------

ALLOWED = [
    "SELECT COUNT(*) FROM substations",
    "SELECT COUNT(*) FROM scada_alarms WHERE resolved = false;",
    "SELECT s.region, COUNT(*) AS outages FROM outages o "
    "JOIN feeders f ON f.feeder_id = o.feeder_id "
    "JOIN substations s ON s.substation_id = f.substation_id "
    "GROUP BY s.region ORDER BY outages DESC",
    "WITH p1 AS (SELECT * FROM outages WHERE severity = 'P1') SELECT COUNT(*) FROM p1",
    "SELECT EXTRACT(YEAR FROM started_at) AS yr, COUNT(*) FROM outages GROUP BY 1",
    "SELECT * FROM outages WHERE rca_summary NOT LIKE '%update%'",
    "SELECT crew_name FROM crew_dispatch_logs GROUP BY crew_name HAVING AVG(response_time_mins) > "
    "(SELECT AVG(response_time_mins) FROM crew_dispatch_logs)",
    "SELECT COUNT(*) FROM public.outages",
]

REJECTED = [
    "SELECT * INTO stolen FROM outages",
    "SELECT username, password_hash FROM users",
    "SELECT pg_sleep(600)",
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
    "SELECT 1; DROP TABLE outages",
    "DELETE FROM outages",
    "UPDATE meters SET status = 'active'",
    "SELECT * FROM checkpoints",
    "SELECT * FROM information_schema.tables",
    "SELECT set_config('statement_timeout', '0', false)",
    "",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_validate_sql_allows_read_queries_on_ops_tables(sql: str) -> None:
    ok, reason = validate_sql(sql)
    assert ok, reason


@pytest.mark.parametrize("sql", REJECTED)
def test_validate_sql_rejects_unsafe_queries(sql: str) -> None:
    ok, _ = validate_sql(sql)
    assert not ok


# ---------------------------------------------------------------------------
# Human-in-the-loop: the hybrid route must not execute SQL before approval
# ---------------------------------------------------------------------------


def test_retrieve_rag_node_never_touches_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import graph as graph_module
    from app.services import rag_service

    sql_calls: list[str] = []

    def _record(*_args, **_kwargs):
        sql_calls.append("called")
        raise RuntimeError("SQL must not run before human approval")

    monkeypatch.setattr(rag_service.SQLService, "generate_sql", _record)
    monkeypatch.setattr(rag_service.SQLService, "execute_sql", _record)
    monkeypatch.setattr(graph_module.sql_service, "execute_sql", _record)
    monkeypatch.setattr(rag_service, "generate", lambda *a, **k: {"text": "{}", "usage": {}})
    monkeypatch.setattr(rag_service, "classify_intent", lambda _q: "hybrid")
    monkeypatch.setattr(
        rag_service,
        "_retrieve",
        lambda q, flags=None: [RetrievedChunk(text="P1 target MTTR is 2 hours", source="doc.txt")],
    )

    update = graph_module.retrieve_rag(
        {"question": "How many P1 outages and what is the dispatch rule?", "flags": {}}
    )
    assert sql_calls == []
    assert update["retrieved_chunks"][0]["source"] == "doc.txt"
    assert "P1 target MTTR" in update["spotlighted_context"]
