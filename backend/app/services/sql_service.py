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


# Tables the Text2SQL model may see and query. Everything else in the
# database (the `users` table with password hashes, LangGraph checkpoint
# tables, Postgres catalogs) is hidden from the schema prompt and rejected
# by the validator.
OPS_TABLES = frozenset(
    {
        "substations",
        "feeders",
        "transformers",
        "meters",
        "outages",
        "scada_alarms",
        "crew_dispatch_logs",
    }
)

_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "merge", "upsert", "drop", "alter", "create",
    "truncate", "grant", "revoke", "into", "copy", "call", "do", "execute",
    "prepare", "deallocate", "lock", "vacuum", "analyze", "reindex", "cluster",
    "refresh", "comment", "set", "reset", "listen", "notify", "unlisten",
    "security", "owner",
)  # fmt: skip

# Functions with side effects, sleeps, file or network access.
_FORBIDDEN_FUNCTIONS = re.compile(
    r"\b(pg_\w+|lo_\w+|dblink\w*|set_config|current_setting|query_to_xml\w*|"
    r"txid_\w+|nextval|setval)\s*\("
)
_CATALOG_REFERENCE = re.compile(r"\b(pg_catalog|information_schema|pg_[a-z_]+)\b")


def _strip_literals_and_comments(sql: str) -> str:
    """Remove comments and quoted literals so keywords inside them are ignored."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r"\$\$.*?\$\$", "''", sql, flags=re.S)
    return sql


def validate_sql(sql: str) -> tuple[bool, str]:
    """Policy check for generated SQL. Returns (ok, reason).

    Defence in depth only: the real guarantee is that `SQLService.execute_sql`
    runs inside a READ ONLY transaction with a statement timeout and a row cap.
    """
    if not sql or not sql.strip():
        return False, "empty query"

    body = _strip_literals_and_comments(sql).strip().rstrip(";").strip()
    lowered = body.lower()

    if ";" in lowered:
        return False, "multiple statements are not allowed"
    if not re.match(r"^\(*\s*(select|with)\b", lowered):
        return False, "only SELECT queries (optionally with a WITH clause) are allowed"
    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return False, f"keyword '{kw.upper()}' is not allowed"
    if _FORBIDDEN_FUNCTIONS.search(lowered):
        return False, "system / side-effecting functions are not allowed"
    if _CATALOG_REFERENCE.search(lowered):
        return False, "system catalogs are not allowed"

    # Every FROM / JOIN target must be an ops table or a CTE defined here.
    cte_names = set(re.findall(r"(?:\bwith|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(", lowered))
    scan = re.sub(r"\b(extract|substring|trim|overlay|position)\s*\([^()]*\)", "0", lowered)
    scan = re.sub(r"\bdistinct\s+from\b", "<>", scan)
    for ref in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_.]*)", scan):
        name = ref.split(".")[-1]
        if ref.count(".") > 1 or (ref.count(".") == 1 and not ref.startswith("public.")):
            return False, f"table '{ref}' is not allowed"
        if name not in OPS_TABLES and name not in cte_names:
            return False, f"table '{name}' is not allowed"
    return True, ""


def is_select_only(sql: str) -> bool:
    """Backwards-compatible boolean wrapper around `validate_sql`."""
    return validate_sql(sql)[0]


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
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            ORDER BY table_name, ordinal_position;
        """, (sorted(OPS_TABLES),))
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
        ok, reason = validate_sql(sql)
        if not ok:
            raise ValueError(f"SQL rejected by policy: {reason}")

        cached = query_cache.get_sql_result(sql)
        if cached is not None:
            return cached

        # Hard guarantees enforced by Postgres itself, whatever the SQL text:
        #   * READ ONLY transaction - any write (including SELECT ... INTO)
        #     fails with "cannot execute ... in a read-only transaction"
        #   * statement_timeout - runaway queries are cancelled
        #   * fetchmany - at most sql_max_rows rows reach Python / the prompt
        conn = psycopg2.connect(
            settings.database_url,
            options=f"-c statement_timeout={int(settings.sql_statement_timeout_ms)}",
        )
        try:
            conn.set_session(readonly=True)
            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchmany(settings.sql_max_rows) if cur.description else []
            conn.rollback()
        finally:
            conn.close()

        result = [_serialize_row(dict(zip(columns, row, strict=True))) for row in rows]
        query_cache.set_sql_result(sql, result)
        return result
