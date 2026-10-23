"""Kontrak provider LLM (G.1 + Fase 1 tools) — read-only, tanpa write action."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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
    #: Fase 1 — tool calls ternormalisasi: [{id, name, arguments(dict)}]
    tool_calls: list = field(default_factory=list)


class BaseLLMProvider(ABC):
    """Provider LLM minimal: `complete` satu shot + `chat` multi-turn (tools)."""

    @abstractmethod
    def complete(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 1000
    ) -> LLMResponse:
        """Panggil LLM. Raise `LLMError` kalau gagal."""
        raise NotImplementedError

    def chat(
        self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1000
    ) -> LLMResponse:
        """Panggilan multi-turn (dipakai agent loop).

        Default: turunkan system+user dari `messages`. Provider yang belum
        mendukung `tools` wajib raise `provider_not_supported`.
        """
        if tools:
            raise LLMError(
                "provider tidak mendukung function calling", "provider_not_supported"
            )
        system = "\n".join(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "system"
        )
        user = "\n".join(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        )
        return self.complete(system, user, max_tokens=max_tokens)


class LLMError(Exception):
    """Error provider dengan kode stabil untuk API/observability."""

    def __init__(self, message: str, code: str = "llm_error"):
        self.message = message
        self.code = code
        super().__init__(message)


__all__ = ("BaseLLMProvider", "LLMError", "LLMResponse")

