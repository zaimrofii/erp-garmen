"""Agent loop AI (Fase 1) — tool calling di balik feature flag.

`run_agent` memanggil LLM dengan daftar tool sesuai role, mengeksekusi tool via
registry (allowlist + trace AIDecisionLog), lalu mengembalikan `AgentResult`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from ..tools import ToolResult, execute_tool, get_schemas_for_role
from .validator import guard_answer

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_TOKENS = 800
TOOL_CONTENT_CAP = 4000

#: Fase demo-ready — pre-flight write detection (diport dari branch feat/agent-tools).
WRITE_PATTERNS = [
    r"\b(ubah|ganti|update|edit|modif|set)\b.*\b(harga|status|data|field|nilai)\b",
    r"\b(hapus|hapuskan|delete|drop|remove|buang)\b",
    r"\b(tambah|create|insert|buat)\b.*\b(produk|order|bundle|customer)\b",
    r"\b(reset|restore|truncate)\b",
]
WRITE_REFUSAL = (
    "Saya hanya bisa membaca data. Saya tidak bisa mengubah, menghapus, atau membuat data. "
    "Untuk perubahan, silakan gunakan halaman yang sesuai di MES."
)


def _is_write_intent(message: str) -> bool:
    """True bila pesan meminta perubahan data (read-only agent harus menolak)."""
    import re

    msg = str(message or "").lower()
    return any(re.search(pattern, msg) for pattern in WRITE_PATTERNS)



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
    clarification: dict | None = None
    blocked_reason: str | None = None
    agent_mode: str = "tools"
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
            "clarification": self.clarification,
            "blocked_reason": self.blocked_reason,
            "agent_mode": self.agent_mode,
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
    history: list[dict] | None = None,
) -> AgentResult:
    """Jalankan loop agent (maks `max_iterations`).

    `history` = 5-10 turn terakhir [{"role","content"}] dari percakapan asli;
    dikirim apa adanya sebagai bagian `messages` (tanpa text-merge).
    """
    config = config or {}
    max_iterations = int(config.get("max_iterations") or DEFAULT_MAX_ITERATIONS)
    max_tokens = int(config.get("max_tokens") or DEFAULT_MAX_TOKENS)
    question = str(config.get("question") or _last_user_text(messages))

    result = AgentResult(tokens={"prompt": 0, "completion": 0, "total_cost_usd": 0})
    started = time.monotonic()

    if _is_write_intent(question):
        result.answer = WRITE_REFUSAL
        result.blocked_reason = "write_intent"
        result.agent_mode = "tools"
        result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
        return result

    provider = _provider(config)
    schemas = get_schemas_for_role(role)

    working = _compose(messages, history)
    pending = config.get("pending") or _load_pending(config)
    if pending:
        choice = resolve_choice(_last_user_text(working), pending.get("matches") or [])
        if choice is not None:
            working.append(
                {
                    "role": "system",
                    "content": (
                        "Pengguna memilih kandidat: "
                        f"{choice.get('code') or choice.get('name') or choice.get('id')}."
                    ),
                }
            )
            _clear_pending(config)
        else:
            result.answer = _clarify_text(pending.get("matches") or [])
            result.clarification = pending
            result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
            return result

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
            if (
                call.get("name") == "find_entity"
                and isinstance(outcome.data, dict)
                and outcome.data.get("ambiguous")
            ):
                state = {
                    "kind": "entity_choice",
                    "matches": list(outcome.data.get("matches") or [])[:5],
                }
                _save_pending(config, state)
                result.answer = _clarify_text(state["matches"])
                result.clarification = state
                result.latency_ms = max(1, int((time.monotonic() - started) * 1000))
                result.messages = working
                return result
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


def _compose(messages: list[dict], history: list[dict] | None) -> list[dict]:
    """System + history asli (maks 10 turn) + pesan baru, tanpa text-merge."""
    items = list(messages or [])
    if not history:
        return items
    head = [item for item in items if item.get("role") == "system"]
    tail = [item for item in items if item.get("role") != "system"]
    turns = [dict(item) for item in history if item.get("content")][-10:]
    return head + turns + tail


ORDINALS = {
    "pertama": 0, "1": 0, "satu": 0,
    "kedua": 1, "2": 1, "dua": 1,
    "ketiga": 2, "3": 2, "tiga": 2,
}


def resolve_choice(message: str, matches: list[dict]) -> dict | None:
    """Pilih kandidat dari jawaban user ("yang pertama", kode, atau nama)."""
    if not matches:
        return None
    lowered = str(message or "").lower()
    for token, index in ORDINALS.items():
        if re.search(rf"\b{token}\b", lowered) and index < len(matches):
            return matches[index]
    for match in matches:
        for key in ("code", "name"):
            value = str(match.get(key) or "").lower()
            if value and value in lowered:
                return match
    return None


def _clarify_text(matches: list[dict]) -> str:
    items = ", ".join(
        f"{index + 1}) {match.get('code') or match.get('name') or match.get('id')}"
        for index, match in enumerate(matches)
    )
    return f"Saya menemukan {len(matches)} kandidat: {items}. Mana yang dimaksud?"


def _pending_scope(config: dict) -> tuple[int, str] | None:
    user_id = config.get("user_id")
    session_id = config.get("session_id")
    if not user_id or not session_id:
        return None
    return int(user_id), str(session_id)


def _save_pending(config: dict, state: dict) -> None:
    scope = _pending_scope(config)
    if scope is None:
        return
    try:
        from ..clarification import pending_state

        pending_state.save(scope[0], scope[1], state)
    except Exception:  # noqa: BLE001 - penyimpanan pending tidak boleh memblokir jawaban
        pass


def _load_pending(config: dict) -> dict | None:
    scope = _pending_scope(config)
    if scope is None:
        return None
    try:
        from ..clarification import pending_state

        return pending_state.load(scope[0], scope[1])
    except Exception:  # noqa: BLE001
        return None


def _clear_pending(config: dict) -> None:
    scope = _pending_scope(config)
    if scope is None:
        return
    try:
        from ..clarification import pending_state

        pending_state.clear(scope[0], scope[1])
    except Exception:  # noqa: BLE001
        pass


__all__ = ("AgentResult", "DEFAULT_MAX_ITERATIONS", "resolve_choice", "run_agent")
