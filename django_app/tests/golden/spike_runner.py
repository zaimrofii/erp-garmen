"""Spike function calling DeepSeek — pengukuran saja (Fase S).

15 pertanyaan golden → LLM memilih 1 dari 3 tool throwaway → tool dieksekusi
terhadap DAL/analytics → hasil dikirim balik → jawaban akhir dinilai terhadap
ground truth.

Jalankan: docker exec -i garmen_django python tests/golden/spike_runner.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone as dt_tz
from pathlib import Path

BASE = Path(__file__).resolve().parent
for parent in (BASE.parent.parent, BASE.parent):
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import httpx  # noqa: E402
import yaml  # noqa: E402
from django.conf import settings  # noqa: E402

from integrations.ai_agent.config import AI_CONFIG  # noqa: E402
from tests.golden import spike_tools  # noqa: E402
from tests.golden.runner_minimal import score  # noqa: E402

BUDGET_USD = 0.05
MAX_TOKENS = 250
SYSTEM_PROMPT = """Kamu asisten MES garmen. Jawab dalam Bahasa Indonesia, singkat.
ATURAN:
- Untuk pertanyaan data, WAJIB panggil salah satu tool yang tersedia.
- Jangan mengarang angka. Kalau tool tidak bisa menjawab, bilang datanya tidak tersedia.
- Jangan pernah menyarankan/melakukan perubahan data (read-only).
- Setelah tool mengembalikan data, jawab dengan angka konkret dari data itu."""

#: Ekspektasi tool per pertanyaan. `None` = tidak ada tool yang bisa menjawab
#: (harus menolak / menyatakan data tidak tersedia, bukan memanggil tool asal).
EXPECTED: dict[str, dict] = {
    "G001": {"tool": "count_records", "must": ["bundle", "sewing-2"]},
    "G002": {"tool": None},  # scrap per work center tidak tersedia di 3 tool
    "G003": {"tool": "list_records", "must": ["order"]},
    "G004": {"tool": None},  # output operator butuh agregasi BundleEvent
    "G005": {"tool": "list_records", "must": ["product", "sale_price"]},
    "G006": {"tool": None},  # stok tidak ada di allowlist entity
    "G007": {"tool": "list_records", "must": ["order", "customer"]},
    "G008": {"tool": "get_metric", "must": ["scrap"]},
    "G009": {"tool": "get_metric", "must": ["lead_time"]},
    "G010": {"tool": "list_records", "must": ["product", "sale_price"]},
    "G011": {"tool": "count_records", "must": ["product"]},
    "G012": {"tool": None},
    "G013": {"tool": None},  # rentang "Januari 2026" tidak ada di enum range
    "G014": {"tool": None},
    "G015": {"tool": "count_records", "must": ["order"]},
}


def _price() -> tuple[float, float]:
    llm = AI_CONFIG["llm"]
    return float(llm["cost_per_1k_prompt_usd"]), float(llm["cost_per_1k_completion_usd"])


def call_llm(messages: list[dict], use_tools: bool = True) -> dict:
    """Satu panggilan DeepSeek (OpenAI-compatible), retry sekali."""
    api_key = str(getattr(settings, "AI_LLM_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("AI_LLM_API_KEY tidak di-set; spike dibatalkan.")
    base = str(getattr(settings, "AI_LLM_BASE_URL", "") or "https://api.deepseek.com/v1").rstrip("/")
    model = str(getattr(settings, "AI_LLM_MODEL", "") or "deepseek-chat")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    if use_tools:
        payload["tools"] = spike_tools.TOOLS_SCHEMA
        payload["tool_choice"] = "auto"

    last_error = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"LLM gagal: {last_error}")


def usage_cost(data: dict) -> float:
    usage = data.get("usage") or {}
    prompt, completion = _price()
    return (
        int(usage.get("prompt_tokens") or 0) / 1000 * prompt
        + int(usage.get("completion_tokens") or 0) / 1000 * completion
    )


def params_match(arguments: dict, must: list[str]) -> bool:
    blob = json.dumps(arguments, ensure_ascii=False).lower()
    return all(token.lower() in blob for token in must)


def run_question(question: dict, model_label: str) -> tuple[dict, float]:
    """Satu pertanyaan = loop maks 3 putaran (tool call → tool result → jawaban)."""
    expected = EXPECTED.get(question["id"], {"tool": None})
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question["q"]},
    ]
    started = time.perf_counter()
    cost = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    tool_name = None
    arguments: dict = {}
    tool_result = None
    answer = ""

    # Loop agent mini: maks 3 putaran (target arsitektur: maks 5).
    for round_index in range(3):
        data = call_llm(messages)
        cost += usage_cost(data)
        usage = data.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            answer = message.get("content") or ""
            break

        messages.append(message)
        for index, call in enumerate(tool_calls):
            function = call.get("function") or {}
            name = function.get("name")
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except ValueError:
                args = {"_raw": raw_args}
            result = spike_tools.execute(name, args)
            if round_index == 0 and index == 0:
                tool_name, arguments, tool_result = name, args, result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or f"call_{round_index}_{index}",
                    "content": json.dumps(result, default=str)[:12000],
                }
            )

    expected_tool = expected.get("tool")
    tool_ok = (tool_name == expected_tool) if expected_tool else (tool_name is None)
    params_ok = params_match(arguments, expected.get("must", [])) if expected_tool else (tool_name is None)
    gt_ok, gt_reason = score(question, answer)

    row = {
        "id": question["id"],
        "q": question["q"],
        "category": question["category"],
        "model": model_label,
        "expected_tool": expected_tool,
        "tool_dipilih": tool_name,
        "parameter": arguments,
        "tool_ok": tool_result.get("ok") if tool_result else None,
        "tool_row_count": (tool_result or {}).get("row_count"),
        "tool_error": (tool_result or {}).get("error"),
        "result_preview": json.dumps(tool_result, default=str)[:700] if tool_result else None,
        "answer": answer[:500],
        "ground_truth": question["ground_truth"],
        "cocok_ground_truth": gt_ok,
        "gt_reason": gt_reason,
        "tool_selection_benar": tool_ok,
        "parameter_benar": bool(params_ok),
        "e2e_benar": bool(tool_ok and params_ok and gt_ok),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost, 8),
    }
    return row, cost


def summarize(rows: list[dict], total_cost: float, model_label: str) -> dict:
    total = len(rows)
    tool_ok = sum(1 for r in rows if r["tool_selection_benar"])
    param_ok = sum(1 for r in rows if r["parameter_benar"])
    e2e = sum(1 for r in rows if r["e2e_benar"])

    per_category: dict[str, dict] = {}
    for row in rows:
        bucket = per_category.setdefault(
            row["category"], {"total": 0, "tool": 0, "param": 0, "e2e": 0}
        )
        bucket["total"] += 1
        bucket["tool"] += int(row["tool_selection_benar"])
        bucket["param"] += int(row["parameter_benar"])
        bucket["e2e"] += int(row["e2e_benar"])

    return {
        "model": model_label,
        "total": total,
        "akurasi_tool_selection_pct": round(tool_ok / total * 100, 1) if total else 0.0,
        "akurasi_parameter_pct": round(param_ok / total * 100, 1) if total else 0.0,
        "akurasi_end_to_end_pct": round(e2e / total * 100, 1) if total else 0.0,
        "benar_tool": tool_ok,
        "benar_parameter": param_ok,
        "benar_e2e": e2e,
        "biaya_usd": round(total_cost, 8),
        "per_kategori": per_category,
        "detail": rows,
    }


def main() -> int:
    questions = yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
    model_label = str(getattr(settings, "AI_LLM_MODEL", "") or "deepseek-chat")

    rows: list[dict] = []
    total_cost = 0.0
    aborted = False
    for question in questions:
        if total_cost > BUDGET_USD:
            aborted = True
            print(f"ABORT: biaya ${total_cost:.6f} melewati budget ${BUDGET_USD}")
            break
        try:
            row, cost = run_question(question, model_label)
        except Exception as exc:  # noqa: BLE001 - satu gagal jangan hentikan run
            expected_tool = EXPECTED.get(question["id"], {}).get("tool")
            row = {
                "id": question["id"],
                "q": question["q"],
                "category": question["category"],
                "model": model_label,
                "expected_tool": expected_tool,
                "tool_dipilih": None,
                "parameter": {},
                "tool_ok": False,
                "tool_row_count": None,
                "tool_error": f"{type(exc).__name__}: {exc}",
                "result_preview": None,
                "answer": "",
                "ground_truth": question["ground_truth"],
                "cocok_ground_truth": False,
                "gt_reason": "error",
                "tool_selection_benar": False,
                "parameter_benar": False,
                "e2e_benar": False,
                "latency_ms": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
            }
            cost = 0.0
            print(f"{question['id']} ERROR {row['tool_error']}")
        total_cost += cost
        rows.append(row)
        print(
            f"{row['id']} tool={str(row['tool_dipilih']):13s} "
            f"sel={int(row['tool_selection_benar'])} par={int(row['parameter_benar'])} "
            f"gt={int(row['cocok_ground_truth'])} e2e={int(row['e2e_benar'])} "
            f"${row['cost_usd']:.6f} :: {row['answer'][:70]}"
        )

    summary = summarize(rows, total_cost, model_label)
    summary["aborted_budget"] = aborted
    summary["budget_usd"] = BUDGET_USD
    summary["generated_at"] = datetime.now(dt_tz.utc).isoformat()
    summary["tools"] = [t["function"]["name"] for t in spike_tools.TOOLS_SCHEMA]

    out = BASE / "spike_results.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"RESULT model={model_label} tool={summary['akurasi_tool_selection_pct']}% "
        f"param={summary['akurasi_parameter_pct']}% e2e={summary['akurasi_end_to_end_pct']}% "
        f"biaya=${total_cost:.6f} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
