"""Provider DeepSeek (G.1) — OpenAI-compatible chat completions."""

from __future__ import annotations

import time

import httpx
from django.conf import settings

from ..config import AI_CONFIG
from .base import BaseLLMProvider, LLMError, LLMResponse

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekProvider(BaseLLMProvider):
    def __init__(self):
        llm_config = AI_CONFIG["llm"]
        self.api_key = str(getattr(settings, "AI_LLM_API_KEY", "") or "").strip()
        self.base_url = (
            str(getattr(settings, "AI_LLM_BASE_URL", "") or "").strip().rstrip("/")
            or DEFAULT_BASE_URL
        )
        self.model = str(
            getattr(settings, "AI_LLM_MODEL", "") or llm_config["model"]
        ).strip()
        self.timeout = float(
            getattr(settings, "AI_LLM_TIMEOUT_SECONDS", llm_config["timeout_seconds"])
        )
        self.temperature = float(llm_config.get("temperature", 0.3))
        self.cost_prompt_per_1k = float(llm_config["cost_per_1k_prompt_usd"])
        self.cost_completion_per_1k = float(llm_config["cost_per_1k_completion_usd"])

    def complete(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 1000
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMError("AI_LLM_API_KEY tidak di-set", "no_api_key")

        start = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": self.temperature,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"LLM HTTP {exc.response.status_code}", "http_error"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("LLM timeout", "timeout") from exc
        except httpx.RequestError as exc:
            raise LLMError("LLM network error", "network_error") from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"LLM error: {type(exc).__name__}", "unknown") from exc

        try:
            text = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Respons LLM tidak valid", "malformed_response") from exc

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = (
            prompt_tokens / 1000 * self.cost_prompt_per_1k
            + completion_tokens / 1000 * self.cost_completion_per_1k
        )

        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost_usd=round(cost, 8),
            model=self.model,
            latency_ms=int((time.monotonic() - start) * 1000),
            raw=data,
        )


__all__ = ("DeepSeekProvider",)
