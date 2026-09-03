import json
import logging
from typing import Literal, cast

from app.config import settings
from app.services.llm_service import generate_with_json
from app.services.query_cache_service import query_cache

Intent = Literal["sql", "rag", "hybrid"]

_INTENT_SYSTEM_PROMPT = """You are an intent classifier for a Grid Operations (electric utility) AI assistant.
Classify the user question into exactly one of these categories:
- "sql": Questions about numerical data, counts, totals, sums, averages, or specific operational facts stored in a database (e.g., "how many P1 outages last quarter", "average MTTR for feeder outages", "which substation has the most transformers", "meters in de-energized status")
- "rag": Questions about concepts, procedures, troubleshooting steps, or general grid-operations knowledge found in documentation or runbooks (e.g., "how to restore a de-energized feeder", "what is a SCADA alarm", "transformer overload response procedure", "P1 outage escalation process")
- "hybrid": Questions that require both operational data from the database AND conceptual knowledge from documentation (e.g., "how many transformer overtemperature alarms occurred last month and what is the recommended remediation")

Respond ONLY with a JSON object in this exact format:
{"intent": "sql"} or {"intent": "rag"} or {"intent": "hybrid"}
"""

logger = logging.getLogger(__name__)


def classify_intent(question: str) -> Intent:
    cached = query_cache.get_intent(question)
    if cached in ("sql", "rag", "hybrid"):
        return cast(Intent, cached)

    try:
        response = generate_with_json(
            system_prompt=_INTENT_SYSTEM_PROMPT,
            user_message=question,
            model=settings.llm_model_grader,
            temperature=0.0,
        )
        raw_text = response.get("text", "")
        parsed = json.loads(raw_text)
        intent = parsed.get("intent", "")

        if intent in ("sql", "rag", "hybrid"):
            query_cache.set_intent(question, intent)
            return cast(Intent, intent)

        logger.error("Invalid intent returned by LLM: %s", intent)
        return "rag"
    except Exception:
        logger.exception("Intent classification failed, falling back to rag")
        return "rag"
