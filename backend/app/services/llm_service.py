from loguru import logger
from openai import OpenAI

from app.config import settings

_DEFAULT_GROQ_URL = "https://api.groq.com/openai/v1"


def _is_real_key(key: str) -> bool:
    """False for empty or obvious `.env.example` placeholder keys (sk-your-..., gsk-your-...)."""
    key = (key or "").strip()
    return bool(key) and not key.lower().startswith(
        ("sk-your", "gsk-your", "your-", "changeme")
    )


# --- Primary: OpenAI, only when a real key is configured --------------------
openai_client: OpenAI | None = (
    OpenAI(api_key=settings.openai_api_key) if _is_real_key(settings.openai_api_key) else None
)

# --- Fallback / OpenAI-free provider: Groq OR any local OpenAI-compatible ---
# server (Ollama, LM Studio, vLLM...) selected via LLM_BASE_URL. Local servers
# don't need a key, so a client is built whenever a key OR a non-Groq URL is set.
_fallback_url = (settings.llm_base_url or _DEFAULT_GROQ_URL).rstrip("/")
_is_local_llm = _fallback_url != _DEFAULT_GROQ_URL
fallback_client: OpenAI | None = None
if _is_real_key(settings.groq_api_key) or _is_local_llm:
    fallback_client = OpenAI(
        api_key=settings.groq_api_key or "local",  # local servers ignore this
        base_url=_fallback_url,
    )

# Back-compat alias (older imports referenced `groq_client`).
groq_client = fallback_client

if openai_client is None and fallback_client is None:
    logger.warning(
        "No usable LLM provider. Set a real OPENAI_API_KEY, a real GROQ_API_KEY, "
        "or LLM_BASE_URL=http://localhost:11434/v1 for a local Ollama server."
    )
elif openai_client is None:
    logger.info(
        "Using fallback LLM: model={} endpoint={}",
        settings.groq_fallback_model,
        _fallback_url,
    )


def _complete(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    json_mode: bool,
) -> dict:
    """Use OpenAI when a real key is set, else the fallback provider (Groq / local)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    kwargs: dict = {"messages": messages, "temperature": temperature}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = None
    if openai_client is not None:
        try:
            response = openai_client.chat.completions.create(model=model, **kwargs)
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenAI completion failed: {}. Falling back to {}.", e, _fallback_url)

    if response is None:
        if fallback_client is None:
            raise RuntimeError(
                "No LLM provider available. Set a real OPENAI_API_KEY or GROQ_API_KEY, "
                "or LLM_BASE_URL=http://localhost:11434/v1 for a local Ollama server."
            )
        # The fallback provider (Groq / Ollama / LM Studio) has its own model set;
        # use GROQ_FALLBACK_MODEL, not the OpenAI model name.
        response = fallback_client.chat.completions.create(
            model=settings.groq_fallback_model, **kwargs
        )

    text = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }
    return {"text": text, "usage": usage}


def generate(
    system_prompt: str, user_message: str, model: str | None = None, temperature: float = 0.0
) -> dict:
    return _complete(
        system_prompt,
        user_message,
        model or settings.llm_model_answer,
        temperature,
        json_mode=False,
    )


def generate_with_json(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    return _complete(
        system_prompt,
        user_message,
        model or settings.llm_model_grader,
        temperature,
        json_mode=True,
    )
