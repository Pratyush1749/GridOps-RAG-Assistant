import datetime
import decimal
import json
import re
import uuid
from typing import Any

import psycopg2
from psycopg2 import sql as pgsql

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

    Defence in depth only. The guarantees come from Postgres at execution
    time: `SQLService.execute_sql` runs as a role that can only SELECT the ops
    tables, inside a READ ONLY transaction with a statement timeout and a row
    cap.
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

    # Every FROM / JOIN target must be an ops table, or a CTE that is in
    # scope at that point (see _check_table_refs).
    scan = _unquote_identifiers(_strip_literals_and_comments(sql)).strip().rstrip(";").lower()
    scan = re.sub(r"\b(extract|substring|trim|overlay|position)\s*\([^()]*\)", "0", scan)
    scan = re.sub(r"\bdistinct\s+from\b", "<>", scan)
    return _check_table_refs(scan)


_IDENT = r"[a-z_][a-z0-9_$]*"
_JOIN_WORDS = {"left", "right", "full", "inner", "outer", "cross", "natural", "lateral", "only"}
_CLAUSE_END = re.compile(
    r"\b(where|group|order|limit|offset|fetch|having|window|union|intersect|except|for)\b"
)


def _unquote_identifiers(sql: str) -> str:
    """Turn "Quoted"."Names" into plain lower-case names so they are checked too."""
    return re.sub(r'"([^"]*)"', lambda m: re.sub(r"\W", "_", m.group(1).lower()), sql)


def _matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top_level_ctes(sql: str) -> tuple[list[tuple[str, str]], str]:
    """Split `WITH a AS (...), b AS (...) <main>` into [(name, body)] and main.

    Returns ([], sql) when the statement has no leading WITH clause.
    """
    m = re.match(r"\s*with\s+", sql)
    if not m:
        return [], sql
    pos = m.end()
    if re.match(r"recursive\b", sql[pos:]):
        raise ValueError("WITH RECURSIVE is not allowed")
    ctes: list[tuple[str, str]] = []
    while True:
        head = re.match(
            rf"\s*({_IDENT})\s*(\([^()]*\))?\s*as\s*(not\s+)?(materialized\s*)?\(", sql[pos:]
        )
        if not head:
            raise ValueError("could not parse the WITH clause")
        name = head.group(1)
        open_idx = pos + head.end() - 1
        close_idx = _matching_paren(sql, open_idx)
        if close_idx == -1:
            raise ValueError("unbalanced parentheses in the WITH clause")
        ctes.append((name, sql[open_idx + 1 : close_idx]))
        pos = close_idx + 1
        comma = re.match(r"\s*,", sql[pos:])
        if not comma:
            return ctes, sql[pos:]
        pos += comma.end()


def _from_clause_tables(sql: str) -> list[str]:
    """Every table name in every FROM clause, including comma lists and JOINs.

    Subqueries are skipped here because their own FROM is found separately.
    """
    names: list[str] = []
    for m in re.finditer(r"\bfrom\b", sql):
        # The FROM clause runs until a clause keyword or a closing paren at depth 0.
        depth, end = 0, len(sql)
        i = m.end()
        while i < len(sql):
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    end = i
                    break
                depth -= 1
            elif depth == 0 and _CLAUSE_END.match(sql, i):
                end = i
                break
            i += 1
        clause = sql[m.end() : end]
        # Blank out nested parentheses, then split on commas and JOIN.
        flat, depth = [], 0
        for ch in clause:
            if ch == "(":
                depth += 1
                flat.append("(" if depth == 1 else " ")
            elif ch == ")":
                depth -= 1
                flat.append(" ")
            else:
                flat.append(ch if depth == 0 else " ")
        for piece in re.split(r",|\bjoin\b", "".join(flat)):
            words = piece.split()
            while words and words[0] in _JOIN_WORDS:
                words.pop(0)
            if not words or words[0].startswith("("):
                continue
            names.append(words[0].rstrip("("))
    return names


def _refs_allowed(sql: str, allowed: set[str]) -> tuple[bool, str]:
    for ref in _from_clause_tables(sql):
        name = ref.split(".")[-1]
        if ref.count(".") > 1 or (ref.count(".") == 1 and not ref.startswith("public.")):
            return False, f"table '{ref}' is not allowed"
        if name not in allowed:
            return False, f"table '{name}' is not allowed"
    return True, ""


def _check_table_refs(sql: str) -> tuple[bool, str]:
    """A CTE name is only in scope after its own definition ends.

    Postgres resolves a name used inside a non-recursive CTE body (or in a
    CTE defined before it) to the real table, so `WITH users AS (SELECT *
    FROM users) ...` reads the real users table. Each body is therefore
    checked against the ops tables plus the CTEs defined before it.
    """
    try:
        ctes, main = _split_top_level_ctes(sql)
    except ValueError as exc:
        return False, str(exc)
    allowed = set(OPS_TABLES)
    for name, body in ctes:
        ok, reason = _refs_allowed(body, allowed)
        if not ok:
            return ok, reason
        allowed.add(name)
    return _refs_allowed(main, allowed)


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
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            ORDER BY table_name, ordinal_position;
        """,
            (sorted(OPS_TABLES),),
        )
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
                f"The model did not return usable SQL. Raw output: {result['text'][:300]!r}"
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
        #   * SET LOCAL ROLE - a role with SELECT on the ops tables only, so
        #     `users` and the checkpoint tables are unreadable even if a query
        #     slips past validate_sql
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
                if settings.sql_reader_role:
                    cur.execute(
                        pgsql.SQL("SET LOCAL ROLE {}").format(
                            pgsql.Identifier(settings.sql_reader_role)
                        )
                    )
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchmany(settings.sql_max_rows) if cur.description else []
            conn.rollback()
        finally:
            conn.close()

        result = [_serialize_row(dict(zip(columns, row, strict=True))) for row in rows]
        query_cache.set_sql_result(sql, result)
        return result
