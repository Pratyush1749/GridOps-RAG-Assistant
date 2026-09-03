import datetime
import decimal
import json
import re
import uuid
from typing import Any

import psycopg2

from app.config import settings
from app.services.llm_service import generate
from app.services.query_cache_service import query_cache


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Serialize all values in a row dict for JSON compatibility."""
    return {k: _serialize_value(v) for k, v in row.items()}


def _first_json_object(text: str) -> str:
    """Return the first balanced {...} span in text, or ''."""
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _parse_sql_payload(text: str) -> tuple[str, str]:
    """Best-effort (sql, explanation) from a possibly-messy LLM reply.

    Small local models rarely return clean JSON, so try, in order:
    JSON as-is -> first {...} block -> a bare `SELECT ... ` statement.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()

    for candidate in (text, _first_json_object(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and str(data.get("sql", "")).strip():
            return str(data["sql"]).strip(), str(data.get("explanation", "")).strip()

    m = re.search(r"(?is)\bselect\b.+?(?:;|$)", text)
    if m:
        return m.group(0).strip().rstrip(";"), "Extracted from model output (no valid JSON)."
    return "", ""


def is_select_only(sql: str) -> bool:
    """Return True if the SQL is a SELECT statement only."""
    cleaned = sql.strip().lower()
    # Must start with select
    if not cleaned.startswith("select"):
        return False
    # Must not contain dangerous keywords
    forbidden = [
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "grant",
        "revoke",
    ]
    for kw in forbidden:
        if re.search(rf"\b{kw}\b", cleaned):
            return False
    return True


class SQLService:
    def __init__(self) -> None:
        self._schema_context: str | None = None

    def _build_schema_context(self) -> str:
        if self._schema_context is not None:
            return self._schema_context

        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        tables: dict[str, list[str]] = {}
        for table, col, dtype in rows:
            tables.setdefault(table, []).append(f"{col} ({dtype})")

        lines = ["Database schema:"]
        for table, cols in tables.items():
            lines.append(f"  {table}: {', '.join(cols)}")

        self._schema_context = "\n".join(lines)
        return self._schema_context

    def generate_sql(self, question: str) -> dict:
        cached = query_cache.get_sql_generation(question)
        if cached is not None:
            return {"sql": cached, "explanation": "Loaded from SQL generation cache."}

        schema = self._build_schema_context()
        system = (
            "You are a SQL expert. Given a database schema and a question, "
            "generate a valid PostgreSQL SELECT query. Return JSON with keys: sql, explanation."
        )
        user = f"{schema}\n\nQuestion: {question}\n\nReturn only the JSON object."
        result = generate(
            system, user, model=settings.sql_model, temperature=settings.sql_temperature
        )
        sql, explanation = _parse_sql_payload(result["text"])
        if not sql:
            raise ValueError(
                "The model did not return usable SQL. Raw output: "
                f"{result['text'][:300]!r}"
            )

        query_cache.set_sql_generation(question, sql)
        return {"sql": sql, "explanation": explanation}

    def execute_sql(self, sql: str) -> list[dict]:
        if not is_select_only(sql):
            raise ValueError("Only SELECT statements are allowed")

        cached = query_cache.get_sql_result(sql)
        if cached is not None:
            return cached

        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = [_serialize_row(dict(zip(columns, row, strict=True))) for row in rows]
        query_cache.set_sql_result(sql, result)
        return result
