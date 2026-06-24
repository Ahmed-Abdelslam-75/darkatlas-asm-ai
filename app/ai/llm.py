"""Factory for the chat model used across the analysis layer.

Provider: Google Gemini (free cloud tier) via langchain-google-genai. We read
the key from settings (env) and never hardcode it. The model id is configurable
(`LLM_MODEL`) and defaults to gemini-2.0-flash. `temperature=0` keeps the
structured-output translation as deterministic as the provider allows.
"""

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from ..config import settings


class LLMNotConfigured(RuntimeError):
    """Raised when an analysis endpoint is called without an API key configured."""


@lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    if not settings.google_api_key:
        raise LLMNotConfigured(
            "GOOGLE_API_KEY is not set; the analysis endpoints are unavailable."
        )
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=0,
        # Gemini 2.5-flash is a "thinking" model: reasoning tokens count toward the
        # output budget, so we give generous headroom or structured output truncates.
        max_output_tokens=8192,
        timeout=90,
        max_retries=2,
    )
