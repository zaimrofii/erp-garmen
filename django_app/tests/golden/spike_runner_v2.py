"""Spike-2 runner: 7 tool generik, skenario A (1 tool) vs B (multi-turn ≤3).

Jalankan: docker exec -i garmen_django python tests/golden/spike_runner_v2.py
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
from tests.golden import spike_tools_v2 as tools  # noqa: E402
from tests.golden.runner_minimal import numbers_in, score  # noqa: E402

#: Sisa budget: total kumulatif tidak boleh > $0.05 (sudah terpakai $0.023135).
BUDGET_USD = 0.026
TOTAL_SPENT = 0.0  # kumulatif run ini; dijaga <= BUDGET_USD (≤ $0.05 total proyek)
MAX_TOKENS = 300
SYSTEM_PROMPT = """Kamu asisten MES garmen. Jawab Bahasa Indonesia, singkat, pakai angka dari tool.
ATURAN:
- WAJIB panggil tool untuk pertanyaan data. Jangan mengarang angka.
- Kalau tool tidak punya datanya, bilang datanya tidak tersedia.
- Read-only: jangan pernah menyarankan/melakukan perubahan data.
- Sebut angka persis seperti yang dikembalikan tool (satuan jelas)."""

#: Ekspektasi tool + token parameter wajib. None = tidak ada tool (harus menolak).
EXPECTED = {
    "G001": {"tool": "count_records", "must": ["bundle", "sewing-2"]},
    "G002": {"tool": "aggregate", "must": ["scrap", "work_center"]},
    "G003": {"tool": "list_records", "must": ["order"]},
    "G004": {"tool": "get_metric", "must": ["operator"]},
    "G005": {"tool": "list_records", "must": ["product", "sale_price"]},
    "G006": {"tool": "get_stock", "must": ["kaos"]},
    "G007": {"tool": "aggregate", "must": ["order", "customer"]},
    "G008": {"tool": "get_metric", "must": ["scrap", "work_center"]},
    "G009": {"tool": "get_metric", "must": ["lead_time"]},
    "G010": {"tool": "list_records", "must": ["product", "sale_price"]},
    "G011": {"tool": "count_records", "must": ["product"]},
    "G012": {"tool": None},
    "G013": {"tool": "get_metric", "must": ["scrap"]},
    "G014": {"tool": None},
    "G015": {"tool": "count_records", "must": ["order"]},
}

#: Tool alternatif yang sama-sama sah (jawaban benar lewat tool lain).
EXPECT_ALT = {
    "G002": {"aggregate", "get_metric"},
    "G013": {"aggregate", "get_metric"},
}

#: Pertanyaan penolakan: eksplorasi read-only sebelum menolak tidak dihitung salah.
REFUSAL_IDS = {"G012", "G014"}

#: Angka_salah yang terbukti artefak parser (manual review, 2026-10-23):
#: A/G005 & A/G014 "250.000,00" terbaca 25000000; B/G001 "SEWING-2" terbaca 2.
ARTIFACT_IDS = {"A": {"G005", "G014"}, "B": {"G001"}}


def _price() -> tuple[float, float]:
    llm = AI_CONFIG["llm"]
    return float(llm["cost_per_1k_prompt_usd"]), float(llm["cost_per_1k_completion_usd"])


def usage_cost(data: dict) -> float:
    usage = data.get("usage") or {}
    prompt, completion = _price()
    return (
        int(usage.get("prompt_tokens") or 0) / 1000 * prompt
        + int(usage.get("completion_tokens") or 0) / 1000 * completion
    )


def call_llm(messages: list[dict], with_tools: bool = True) -> dict:
    api_key = str(getattr(settings, "AI_LLM_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("AI_LLM_API_KEY tidak di-set; spike dibatalkan.")
    base = str(getattr(settings, "AI_LLM_BASE_URL", "") or "https://api.deepseek.com/v1").rstrip("/")
    model = str(getattr(settings, "AI_LLM_MODEL", "") or "deepseek-chat")
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": MAX_TOKENS}
    if with_tools:
        payload["tools"] = tools.TOOLS_SCHEMA
        payload["tool_choice"] = "auto"

    last_error = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=90) as client:
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


def params_match(arguments: dict, must: list[str]) -> bool:
    blob = json.dumps(arguments, ensure_ascii=False).lower()
    return all(token.lower() in blob for token in must)


def _result_numbers(results: list[dict]) -> list[float]:
    values: list[float] = []
    for result in results:
        for number in numbers_in(json.dumps(result, default=str)):
            values.append(number)
    return values


def wrong_numbers(answer: str, results: list[dict]) -> list[float]:
    """Angka jawaban yang tidak plausibel terhadap hasil tool.

    Heuristik: angka dijawab dianggap salah bila di luar rentang [min,max] nilai
    numerik hasil tool (jadi hasil hitungan seperti rata-rata tetap lolos), atau
    bila tool tidak mengembalikan angka sama sekali. Tahun 2000–2100 diabaikan.
    """
    answered = [n for n in numbers_in(answer) if not (2000 <= n <= 2100)]
    if not answered:
        return []
    pool = _result_numbers(results)
    if not pool:
        return answered
    low, high = min(pool), max(pool)
    span = max(high - low, 1.0)
    margin = span * 0.25
    return [n for n in answered if n < low - margin or n > high + margin]


def run_question(question: dict, scenario: str, model_label: str) -> tuple[dict, float]:
    """Skenario A: 1 putaran tool. Skenario B: maks 3 putaran tool."""
    expected = EXPECTED.get(question["id"], {"tool": None})
    max_rounds = 1 if scenario == "A" else 3
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question["q"]},
    ]
    started = time.perf_counter()
    cost = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    tool_names: list[str] = []
    arguments_list: list[dict] = []
    results: list[dict] = []
    answer = ""

    for _ in range(max_rounds):
        data = call_llm(messages, with_tools=True)
        cost += usage_cost(data)
        usage = data.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            answer = message.get("content") or ""
            break
        messages.append(message)
        for index, call in enumerate(calls):
            function = call.get("function") or {}
            name = function.get("name")
            raw = function.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except ValueError:
                args = {"_raw": raw}
            result = tools.execute(name, args)
            tool_names.append(name)
            arguments_list.append(args)
            results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or f"call_{index}",
                    "content": json.dumps(result, default=str)[:12000],
                }
            )
    else:
        # Putaran habis → paksa jawaban tanpa tool.
        data = call_llm(messages, with_tools=False)
        cost += usage_cost(data)
        usage = data.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        answer = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    expected_tool = expected.get("tool")
    first_tool = tool_names[0] if tool_names else None
    first_args = arguments_list[0] if arguments_list else {}
    if question["id"] in REFUSAL_IDS:
        tool_ok, params_ok = True, True
    else:
        allowed = EXPECT_ALT.get(question["id"], {expected_tool} if expected_tool else set())
        if allowed:
            tool_ok = any(name in allowed for name in tool_names)
            params_ok = params_match(first_args, expected.get("must", []))
        else:
            tool_ok, params_ok = (not tool_names), (not tool_names)
    gt_ok, gt_reason = score(question, answer)
    bad = wrong_numbers(answer, results)

    row = {
        "id": question["id"],
        "q": question["q"],
        "category": question["category"],
        "scenario": scenario,
        "model": model_label,
        "expected_tool": expected_tool,
        "tools_dipilih": tool_names,
        "parameter": first_args,
        "tool_errors": [r.get("error") for r in results if r.get("error")],
        "tool_row_counts": [r.get("row_count") for r in results],
        "answer": answer[:600],
        "ground_truth": question["ground_truth"],
        "cocok_ground_truth": gt_ok,
        "gt_reason": gt_reason,
        "tool_selection_benar": tool_ok,
        "parameter_benar": bool(params_ok),
        "e2e_benar": bool(tool_ok and params_ok and gt_ok),
        "angka_salah": bad,
        "angka_salah_count": len(bad),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tool_calls": len(tool_names),
        "cost_usd": round(cost, 8),
    }
    return row, cost


SMOKE_CASES: list[tuple[str, dict]] = [
    ("list_records", {"entity": "product", "filters": {"is_active": True}, "sort": "-sale_price", "limit": 1}),
    ("count_records", {"entity": "bundle", "filters": {"state": "REWORK"}}),
    ("get_record", {"entity": "order", "id_or_code": "S00004", "include": ["lines"]}),
    ("aggregate", {"entity": "scrap", "field": "qty", "op": "sum", "group_by": "work_center"}),
    ("get_metric", {"name": "garment.oee", "range": {"from": "2026-10-19", "to": "2026-10-22"}}),
    ("get_stock", {"product_code": "ODOO-65"}),
    ("find_entity", {"entity": "work_center", "text": "SEWING-2"}),
]


def smoke_test() -> None:
    """Jalankan tiap tool 1x SEBELUM LLM; gagal = stop."""
    failures = []
    for name, args in SMOKE_CASES:
        result = tools.execute(name, args)
        status = "OK" if result.get("ok") else "FAIL"
        print(f"SMOKE {name:15s} {status} {str(result.get('error') or '')[:80]}")
        if not result.get("ok"):
            failures.append((name, result.get("error")))
    if failures:
        raise SystemExit(f"Smoke test tool gagal: {failures}")


def summarize(rows: list[dict], scenario: str, total_cost: float, model_label: str) -> dict:
    total = len(rows)
    tool_ok = sum(1 for r in rows if r["tool_selection_benar"])
    param_ok = sum(1 for r in rows if r["parameter_benar"])
    e2e = sum(1 for r in rows if r["e2e_benar"])
    wrong = sum(
        1
        for r in rows
        if r["angka_salah_count"] > 0 and not r.get("angka_salah_artifact")
    )

    per_category: dict[str, dict] = {}
    for row in rows:
        bucket = per_category.setdefault(
            row["category"], {"total": 0, "tool": 0, "param": 0, "e2e": 0, "wrong": 0}
        )
        bucket["total"] += 1
        bucket["tool"] += int(row["tool_selection_benar"])
        bucket["param"] += int(row["parameter_benar"])
        bucket["e2e"] += int(row["e2e_benar"])
        bucket["wrong"] += int(row["angka_salah_count"] > 0 and not row.get("angka_salah_artifact"))

    return {
        "scenario": scenario,
        "model": model_label,
        "total": total,
        "tool_pct": round(tool_ok / total * 100, 1) if total else 0.0,
        "param_pct": round(param_ok / total * 100, 1) if total else 0.0,
        "e2e_pct": round(e2e / total * 100, 1) if total else 0.0,
        "angka_salah_pct": round(wrong / total * 100, 1) if total else 0.0,
        "benar_tool": tool_ok,
        "benar_param": param_ok,
        "benar_e2e": e2e,
        "biaya_usd": round(total_cost, 8),
        "per_kategori": per_category,
        "detail": rows,
    }


def run_scenario(scenario: str, questions: list[dict], model_label: str) -> tuple[dict, float]:
    global TOTAL_SPENT
    rows: list[dict] = []
    total_cost = 0.0
    aborted = False
    for question in questions:
        if TOTAL_SPENT > BUDGET_USD:
            aborted = True
            print(f"ABORT skenario {scenario}: kumulatif ${TOTAL_SPENT:.6f} > ${BUDGET_USD}")
            break
        try:
            row, cost = run_question(question, scenario, model_label)
        except Exception as exc:  # noqa: BLE001 - satu gagal jangan hentikan run
            print(f"{scenario} {question['id']} ERROR {type(exc).__name__}: {exc}")
            row = {
                "id": question["id"],
                "q": question["q"],
                "category": question["category"],
                "scenario": scenario,
                "model": model_label,
                "expected_tool": EXPECTED.get(question["id"], {}).get("tool"),
                "tools_dipilih": [],
                "parameter": {},
                "tool_errors": [f"{type(exc).__name__}: {exc}"],
                "tool_row_counts": [],
                "answer": "",
                "ground_truth": question["ground_truth"],
                "cocok_ground_truth": False,
                "gt_reason": "error",
                "tool_selection_benar": False,
                "parameter_benar": False,
                "e2e_benar": False,
                "angka_salah": [],
                "angka_salah_count": 0,
                "latency_ms": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "tool_calls": 0,
                "cost_usd": 0.0,
            }
            cost = 0.0
        total_cost += cost
        TOTAL_SPENT += cost
        rows.append(row)
        print(
            f"{scenario} {row['id']} tool={str(row['tools_dipilih'][:1]):38s} "
            f"sel={int(row['tool_selection_benar'])} par={int(row['parameter_benar'])} "
            f"gt={int(row['cocok_ground_truth'])} e2e={int(row['e2e_benar'])} "
            f"salah={row['angka_salah_count']} ${row['cost_usd']:.6f}"
        )
    summary = summarize(rows, scenario, total_cost, model_label)
    summary["aborted_budget"] = aborted
    return summary, total_cost


def rescore(payload: dict, questions: list[dict]) -> dict:
    """Hitung ulang skor dari jawaban tersimpan (tanpa panggilan LLM).

    Dipakai setelah perbaikan parser angka & aturan skor (tool alternatif,
    pertanyaan penolakan, artefak angka). Biaya $0.
    """
    by_id = {question["id"]: question for question in questions}
    for key, scenario in (("skenario_A", "A"), ("skenario_B", "B")):
        rows = payload[key]["detail"]
        for row in rows:
            question = by_id[row["id"]]
            gt_ok, reason = score(question, row.get("answer") or "")
            row["cocok_ground_truth"] = gt_ok
            row["gt_reason"] = reason

            if row["id"] in REFUSAL_IDS:
                tool_ok, params_ok = True, True
            else:
                expected = EXPECTED.get(row["id"], {})
                expected_tool = expected.get("tool")
                allowed = EXPECT_ALT.get(
                    row["id"], {expected_tool} if expected_tool else set()
                )
                chain = row.get("tools_dipilih") or []
                if allowed:
                    tool_ok = any(name in allowed for name in chain)
                    params_ok = params_match(row.get("parameter") or {}, expected.get("must", []))
                else:
                    tool_ok, params_ok = (not chain), (not chain)

            row["tool_selection_benar"] = bool(tool_ok)
            row["parameter_benar"] = bool(params_ok)
            row["e2e_benar"] = bool(tool_ok and params_ok and gt_ok)
            row["angka_salah_artifact"] = row["id"] in ARTIFACT_IDS.get(scenario, set())

        cost = float(payload[key].get("biaya_usd") or 0)
        model = payload[key].get("model") or payload.get("model") or "deepseek-chat"
        payload[key] = summarize(rows, scenario, cost, model)

    payload["rescored_offline"] = True
    payload["rescored_at"] = datetime.now(dt_tz.utc).isoformat()
    return payload


def main() -> int:
    questions = yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
    model_label = str(getattr(settings, "AI_LLM_MODEL", "") or "deepseek-chat")
    out = BASE / "spike_results_v2.json"

    if "--rescore" in sys.argv:
        payload = json.loads(out.read_text(encoding="utf-8"))
        payload = rescore(payload, questions)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        for name in ("A", "B"):
            summary = payload[f"skenario_{name}"]
            print(
                f"RESCORE {name}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
                f"e2e={summary['e2e_pct']}% angka_salah={summary['angka_salah_pct']}%"
            )
        return 0

    smoke_test()

    print(f"model={model_label} questions={len(questions)} budget=${BUDGET_USD}")
    summary_a, cost_a = run_scenario("A", questions, model_label)
    summary_b, cost_b = run_scenario("B", questions, model_label)

    payload = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "model": model_label,
        "budget_usd": BUDGET_USD,
        "total_cost_usd": round(cost_a + cost_b, 8),
        "kumulatif_proyek_usd": round(0.023135 + cost_a + cost_b, 8),
        "tools": [t["function"]["name"] for t in tools.TOOLS_SCHEMA],
        "skenario_A": summary_a,
        "skenario_B": summary_b,
    }
    out = BASE / "spike_results_v2.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    for name, summary in (("A", summary_a), ("B", summary_b)):
        print(
            f"SKENARIO {name}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
            f"e2e={summary['e2e_pct']}% angka_salah={summary['angka_salah_pct']}% "
            f"biaya=${summary['biaya_usd']:.6f}"
        )
    print(
        f"TOTAL biaya run ${cost_a + cost_b:.8f} | kumulatif ${0.023135 + cost_a + cost_b:.8f} "
        f"-> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
