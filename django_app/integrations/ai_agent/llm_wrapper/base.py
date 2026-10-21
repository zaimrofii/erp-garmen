"""Kontrak provider LLM (G.1) — read-only, tanpa write action."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Hasil satu panggilan LLM (biaya & token sudah dihitung provider)."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    model: str
    latency_ms: int
    raw: dict


class BaseLLMProvider(ABC):
    """Provider LLM minimal: satu metode `complete` (tanpa tools/write)."""

    @abstractmethod
    def complete(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 1000
    ) -> LLMResponse:
        """Panggil LLM. Raise `LLMError` kalau gagal."""
        raise NotImplementedError


class LLMError(Exception):
    """Error provider dengan kode stabil untuk API/observability."""

    def __init__(self, message: str, code: str = "llm_error"):
        self.message = message
        self.code = code
        super().__init__(message)


__all__ = ("BaseLLMProvider", "LLMError", "LLMResponse")
