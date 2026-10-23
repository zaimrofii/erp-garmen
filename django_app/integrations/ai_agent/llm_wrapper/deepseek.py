"""Provider DeepSeek (G.1) — OpenAI-compatible chat completions."""

from __future__ import annotations

import time

import httpx
from django.conf import settings

from ..config import AI_CONFIG
from .base import BaseLLMProvider, LLMError, LLMResponse

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


def _normalize_tool_calls(raw_calls: list) -> list[dict]:
    """Seragamkan tool_calls OpenAI → [{id, name, arguments(dict)}]."""
    import json

    normalized: list[dict] = []
    for index, call in enumerate(raw_calls or []):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        raw_arguments = function.get("arguments") or "{}"
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except ValueError:
                arguments = {"_raw": raw_arguments}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            arguments = {}
        normalized.append(
            {
                "id": str(call.get("id") or f"call_{index}"),
                "name": str(function.get("name") or ""),
                "arguments": arguments,
            }
        )
    return normalized


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
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=None,
            max_tokens=max_tokens,
        )

    def chat(
        self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1000
    ) -> LLMResponse:
        """Multi-turn + function calling (format OpenAI-compatible)."""
        if not self.api_key:
            raise LLMError("AI_LLM_API_KEY tidak di-set", "no_api_key")

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        start = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
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
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Respons LLM tidak valid", "malformed_response") from exc
        if not isinstance(message, dict):
            raise LLMError("Respons LLM tidak valid", "malformed_response")

        text = str(message.get("content") or "")
        tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
        if not text and not tool_calls:
            raise LLMError("Respons LLM kosong", "empty_response")

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
            tool_calls=tool_calls,
        )


__all__ = ("DeepSeekProvider",)
