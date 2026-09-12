import datetime
import decimal
import json
import uuid
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.config import settings
from app.core.state import GraphState
from app.models import RetrievedChunk
from app.security.spotlighting import build_spotlighted_context
from app.services.llm_service import generate
from app.services.rag_service import run_rag
from app.services.router_service import classify_intent
from app.services.sql_service import SQLService

sql_service = SQLService()


def _safe_json_default(obj: Any) -> Any:
    """Fallback serializer for non-JSON-native types."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, datetime.time):
        return obj.isoformat()
    if isinstance(obj, datetime.timedelta):
        return str(obj)
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _safe_json_dumps(obj: Any, **kwargs: Any) -> str:
    """json.dumps with a safe fallback for exotic types."""
    return json.dumps(obj, default=_safe_json_default, **kwargs)


def route_intent(state: GraphState) -> dict:
    """LLM-based intent router for sql/rag/hybrid."""
    intent = classify_intent(state["question"])
    return {"intent": intent}


def retrieve_rag(state: GraphState) -> dict:
    response = run_rag(state["question"], flags=state.get("flags", {}))
    # response.sources is a deduplicated list[str] of filenames only - it was
    # previously used to build fake chunks whose .text was the filename
    # itself, so the hybrid prompt's "Retrieved Documents" section never
    # actually contained document text. Use the real chunk previews
    # (text/source/score), which rag_service already computed, instead.
    chunks = [
        RetrievedChunk(text=c.text, source=c.source, score=c.score)
        for c in response.metadata.retrieved_chunks
    ]
    chunk_dicts = [c.model_dump() for c in chunks]
    return {
        # Stored as plain dicts, not RetrievedChunk instances: GraphState is
        # checkpointed via msgpack, which warns (and will eventually refuse)
        # on unregistered custom types. build_spotlighted_context() below
        # uses the live `chunks` objects directly rather than round-tripping
        # through the persisted state.
        "retrieved_chunks": chunk_dicts,
        "chunk_previews": chunk_dicts,
        "spotlighted_context": build_spotlighted_context(chunks),
        "rag_cache_hit": response.cache_hit,
    }


def generate_sql_node(state: GraphState) -> dict:
    try:
        result = sql_service.generate_sql(state["question"])
        return {
            "generated_sql": result["sql"],
            "sql_explanation": result["explanation"],
        }
    except Exception as exc:  # noqa: BLE001 - weak local models often fail here
        return {
            "generated_sql": "",
            "sql_explanation": f"SQL generation failed: {exc}",
            "final_answer": (
                "I couldn't turn that into a database query. "
                "Try rephrasing, or use a stronger model (GROQ_FALLBACK_MODEL)."
            ),
        }


def request_sql_approval(state: GraphState) -> dict:
    # Nothing to approve if generation failed — skip the human-in-the-loop pause.
    if not state.get("generated_sql"):
        return {"sql_approved": False}
    approval = interrupt(
        {
            "type": "sql_approval_required",
            "sql": state["generated_sql"],
            "explanation": state["sql_explanation"],
        }
    )
    return {"sql_approved": approval.get("approved", False)}


def execute_sql(state: GraphState) -> dict:
    """Execute approved SQL and store results."""
    if state.get("final_answer"):  # generation already produced a message
        return {"sql_rows": []}
    if not state.get("sql_approved"):
        return {"sql_rows": [], "final_answer": "SQL query was not approved."}

    sql = state.get("generated_sql") or ""
    try:
        rows = sql_service.execute_sql(sql)
        return {"sql_rows": rows}
    except Exception as exc:
        return {"sql_rows": [], "final_answer": f"SQL execution failed: {exc}"}


def generate_answer(state: GraphState) -> dict:
    intent = state.get("intent", "rag")

    if intent == "sql":
        rows = state.get("sql_rows", [])
        if not rows:
            return {
                "final_answer": state.get("final_answer", "No results."),
                "sources": ["database query"],
                "confidence": 0.9,
            }
        answer = f"Query results:\n```\n{_safe_json_dumps(rows, indent=2)}\n```"
        return {
            "final_answer": answer,
            "sources": ["database query"],
            "confidence": 0.9,
        }

    if intent == "hybrid":
        return _generate_hybrid_answer(state)

    response = run_rag(state["question"], flags=state.get("flags", {}))
    chunk_previews = [chunk.model_dump() for chunk in response.metadata.retrieved_chunks]

    return {
        "final_answer": response.answer,
        "sources": response.sources,
        "confidence": response.confidence,
        # "cache_hit" (unqualified) isn't a GraphState field and would be
        # silently dropped by LangGraph's state merge; "rag_cache_hit" is
        # declared and is what api/query.py:_build_response reads.
        "rag_cache_hit": response.cache_hit,
        "chunk_previews": chunk_previews,
        # Surface Self-RAG telemetry so the API can include it in the response.
        "reflection_iterations": response.metadata.reflection_iterations,
        "refined_question": response.metadata.refined_question,
    }


def _generate_hybrid_answer(state: GraphState) -> dict:
    rows = state.get("sql_rows", [])
    rag_context = state.get("spotlighted_context", "")

    sql_section = ""
    if rows:
        sql_section = (
            f"=== Database Query Results ===\n```\n{_safe_json_dumps(rows, indent=2)}\n```\n"
        )

    rag_section = f"=== Retrieved Documents ===\n{rag_context}\n" if rag_context else ""

    system = (
        "You are an AI assistant. Synthesize database query results and "
        "retrieved documents into a single coherent answer. Cite sources using "
        "[database query] for SQL results and [source_name] for documents."
    )
    user_msg = f"{sql_section}{rag_section}\n\nQuestion: {state['question']}"

    result = generate(system, user_msg)
    doc_sources = list({c["source"] for c in state.get("retrieved_chunks", [])})
    return {
        "final_answer": result["text"],
        "sources": ["database query"] + doc_sources,
        "confidence": 0.85,
    }


def finalize(state: GraphState) -> dict:
    return {}


def _get_checkpointer():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    saver = PostgresSaver(conn=conn)
    saver.setup()
    return saver


def build_graph():

    builder = StateGraph(GraphState)
    builder.add_node("route_intent", route_intent)
    builder.add_node("retrieve_rag", retrieve_rag)
    builder.add_node("generate_sql_node", generate_sql_node)
    builder.add_node("request_sql_approval", request_sql_approval)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("generate_answer", generate_answer)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        lambda s: s.get("intent", "rag"),
        {"sql": "generate_sql_node", "rag": "generate_answer", "hybrid": "retrieve_rag"},
    )
    builder.add_edge("retrieve_rag", "generate_sql_node")
    builder.add_edge("generate_sql_node", "request_sql_approval")
    builder.add_edge("request_sql_approval", "execute_sql")
    builder.add_edge("execute_sql", "generate_answer")
    builder.add_edge("generate_answer", "finalize")
    builder.add_edge("finalize", END)

    checkpointer = _get_checkpointer()
    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Lazy singleton — built on first use so import doesn't crash if DB is down
# ---------------------------------------------------------------------------

_graph_instance = None


def get_graph():
    """Return the compiled LangGraph, building it on first call."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_graph()
    return _graph_instance


# Legacy module-level alias kept for backwards compatibility.
# Accessing `graph` will trigger a build only if the module is imported after
# the database is ready (e.g. inside a FastAPI lifespan / route handler).
class _LazyGraph:
    """Proxy that defers build_graph() until first attribute access."""

    def __getattr__(self, name):
        return getattr(get_graph(), name)

    def invoke(self, *args, **kwargs):
        return get_graph().invoke(*args, **kwargs)

    def stream(self, *args, **kwargs):
        return get_graph().stream(*args, **kwargs)


graph = _LazyGraph()
