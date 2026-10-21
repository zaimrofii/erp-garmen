"""Factory provider LLM (G.1) — dipilih lewat `AI_LLM_PROVIDER`."""

from __future__ import annotations

from django.conf import settings

from ..config import AI_CONFIG
from .base import BaseLLMProvider
from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider


def get_llm_provider() -> BaseLLMProvider:
    provider = str(
        getattr(settings, "AI_LLM_PROVIDER", "") or AI_CONFIG["llm"]["provider"]
    ).strip().lower()

    if provider == "deepseek":
        return DeepSeekProvider()
    if provider == "gemini":
        return GeminiProvider()
    raise ValueError(f"AI_LLM_PROVIDER tidak dikenal: {provider}")


__all__ = ("get_llm_provider",)
