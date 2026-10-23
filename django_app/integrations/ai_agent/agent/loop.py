"""Agent loop AI (Fase 1) — tool calling di balik feature flag.

`run_agent` memanggil LLM dengan daftar tool sesuai role, mengeksekusi tool via
registry (allowlist + trace AIDecisionLog), lalu mengembalikan `AgentResult`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..tools import ToolResult, execute_tool, get_schemas_for_role
from .validator import guard_answer

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_TOKENS = 800
TOOL_CONTENT_CAP = 4000


@dataclass
class AgentResult:
    answer: str = ""
    tool_calls: list = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    iterations: int = 0
    error: str | None = None
    validator: dict | None = None
    messages: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "iterations": self.iterations,
            "error": self.error,
            "validator": self.validator,
        }


def _provider(config: dict):
    if config.get("provider") is not None:
        return config["provider"]
    from ..llm_wrapper.factory import get_llm_provider

    return get_llm_provider()


def _assistant_message(text: str, calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": text or "",
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("arguments") or {}, default=str),
                },
            }
            for call in calls
        ],
    }


def run_agent(
    messages: list[dict],
    role: str,
    user=None,
    config: dict | None = None,
) -> AgentResult:
    """Jalankan loop agent (maks `max_iterations`)."""
    config = config or {}
    max_iterations = int(config.get("max_iterations") or DEFAULT_MAX_ITERATIONS)
    max_tokens = int(config.get("max_tokens") or DEFAULT_MAX_TOKENS)
    question = str(config.get("question") or _last_user_text(messages))
    provider = _provider(config)
    schemas = get_schemas_for_role(role)

    result = AgentResult(tokens={"prompt": 0, "completion": 0, "total_cost_usd": 0})
    started = time.monotonic()
    working = list(messages)

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration
        try:
            response = provider.chat(working, tools=schemas, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 - error jadi hasil, bukan 500
            result.error = _error_code(exc)
            result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
            return result

        result.tokens["prompt"] += response.prompt_tokens
        result.tokens["completion"] += response.completion_tokens
        result.cost_usd += float(response.total_cost_usd or 0)
        result.tokens["total_cost_usd"] = round(result.cost_usd, 8)

        if not response.tool_calls:
            final, verdict = guard_answer(response.text, result.tool_calls, question)
            result.answer = final
            result.validator = verdict
            result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
            result.messages = working
            return result

        working.append(_assistant_message(response.text, response.tool_calls))
        for call in response.tool_calls:
            outcome = execute_tool(call["name"], call.get("arguments"), role, user)
            result.tool_calls.append(_trace(call, outcome))
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(outcome.to_dict(), default=str)[:TOOL_CONTENT_CAP],
                }
            )

    result.error = "max_iterations"
    result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
    result.messages = working
    return result


def _trace(call: dict, outcome: ToolResult) -> dict:
    data = outcome.data if isinstance(outcome.data, dict) else {}
    return {
        "id": call.get("id"),
        "tool": call.get("name"),
        "args": call.get("arguments") or {},
        "row_count": outcome.row_count,
        "error": outcome.error,
        "executed": outcome.error is None,
        "result": data,
        "warnings": list(outcome.warnings),
    }


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "code", "") or type(exc).__name__)


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


__all__ = ("AgentResult", "DEFAULT_MAX_ITERATIONS", "run_agent")
