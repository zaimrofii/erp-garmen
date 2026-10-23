"""Runner validasi: 2 model × 3 run × mode B pada TUNING SET (20).

Biaya dicatat per panggilan; abort bila > $0.50. Held-out tidak dijalankan di sini.
Jalankan: docker exec -i garmen_django python tests/golden/validation_runner.py --model gemini
"""

from __future__ import annotations

import json
import os
import re
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
from django.utils import timezone  # noqa: E402

from integrations.ai_agent.config import AI_CONFIG  # noqa: E402
from tests.golden import spike_tools_v4 as tools  # noqa: E402
from tests.golden.spike_runner_v3 import (  # noqa: E402
    _derived_percentages,
    _subset_stats,
    check_ground_truth,
    load_rules,
    numbers_in_results,
    params_match_rules,
    parse_numbers,
    wrong_numbers,
)

BUDGET_USD = float(os.environ.get("SPIKE_BUDGET", "0.04"))
TOTAL_SPENT = 0.0
# Biaya kumulatif sebelum putaran perbaikan A (dari fase_validasi_2026-10-23).
PREVIOUS_USD = 0.19474412
MAX_ROUNDS = 3
MAX_TOKENS = 250
TOOL_CONTENT_CAP = 5000

MODELS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_attr": "AI_LLM_API_KEY",
        "price": (0.00014, 0.00028),
    },
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "key_attr": "AI_LLM_GEMINI_API_KEY",
        "price": (0.00010, 0.00040),
    },
}

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
    "G016": {"tool": "list_records", "must": ["product", "sale_price"]},
    "G017": {"tool": "count_records", "must": ["product"]},
    "G018": {"tool": "count_records", "must": ["order"]},
    "G019": {"tool": "count_records", "must": ["bundle", "sewing-2"]},
    "G020": {"tool": "aggregate", "must": ["customer"]},
    "G021": {"tool": "count_records", "must": ["bundle", "qc-1"]},
    "G022": {"tool": "aggregate", "must": ["scrap", "qc-1"]},
    "G023": {"tool": "count_records", "must": ["order"]},
    "G024": {"tool": "aggregate_operator", "must": []},
    "G025": {"tool": "get_stock", "must": ["odoo-65"]},
    "G026": {"tool": "count_records", "must": ["customer"]},
    "G027": {"tool": None},
    "G028": {"tool": "get_metric", "must": ["scrap"]},
    "G029": {"tool": None},
    "G030": {"tool": "count_records", "must": ["bundle"]},
}

EXCLUDED = {"G004", "G008"}
EXPECT_ALT = {"G002": {"aggregate", "get_metric"}, "G013": {"aggregate", "get_metric"},
              "G020": {"aggregate", "list_records"}, "G022": {"aggregate", "get_metric"},
              "G028": {"aggregate", "get_metric"}}
REFUSAL_IDS = {"G012", "G014", "G029"}
BLOCKED_ANSWER = (
    "Angka yang dihasilkan tidak konsisten dengan data. Coba tanyakan lebih spesifik."
)


def system_prompt() -> str:
    today = timezone.localdate().isoformat()
    return f"""Kamu asisten MES garmen. Hari ini {today} (WIB).
ATURAN:
- WAJIB pakai tool untuk pertanyaan data; jangan menghitung/mengarang sendiri.
- Jawab SEMUA klausa pertanyaan (dipisah "dan", "lalu", koma) dalam satu jawaban.
- Untuk "minggu ini" isi date_from awal minggu; "bulan ini" awal bulan; snapshot kosongkan tanggal.
- Jika hasil tool punya `stats`, GUNAKAN field sesuai pertanyaan: "rata-rata" -> stats.avg;
  "tertinggi"/"termahal" -> stats.max; "terendah"/"termurah" -> stats.min;
  "terbaru"/"terakhir" -> stats.latest. JANGAN memilih field lain.
- Jika `stats.count` = 0 atau hasil tool kosong, jawab "Tidak ada data untuk periode itu."
  JANGAN mengarang angka.
- Jika pertanyaan menyebut periode tertentu ("minggu ini", "bulan ini", "hari ini",
  "7 hari terakhir") DAN hasil tool menunjukkan `stats.count = 0` atau `row_count = 0`
  untuk periode ITU, jawab "Tidak ada data untuk [periode] itu." JANGAN menjawab angka
  dari periode lain (mis. all-time).
- Jika tool yang dibutuhkan tidak tersedia, jawab "Informasi ini belum bisa diakses dari sistem."
- Read-only: jangan menyarankan/melakukan perubahan data."""


def expected_stat(question_text: str) -> str | None:
    """Field `stats` yang diminta pertanyaan (None bila pertanyaan tidak minta satu field)."""
    text = (question_text or "").lower()
    if "rata-rata" in text or "rata rata" in text:
        return "avg"
    if "tertinggi" in text or "termahal" in text or "paling mahal" in text:
        return "max"
    if "terendah" in text or "termurah" in text or "paling murah" in text:
        return "min"
    if "terbaru" in text or "terakhir" in text:
        return "latest"
    return None


def latest_stats(results: list[dict]) -> dict | None:
    for result in reversed(results):
        if isinstance(result, dict) and isinstance(result.get("stats"), dict):
            return result["stats"]
    return None


def close_enough(value: float, candidates: list[float], rules: dict) -> bool:
    tolerance = float((rules.get("tolerance") or {}).get("approx") or 0.02)
    for candidate in candidates:
        limit = max(abs(candidate) * tolerance, 0.01)
        if abs(value - candidate) <= limit:
            return True
    return False


def _matches_pool(value: float, pool: list[float], rules: dict) -> bool:
    """Exact untuk bilangan bulat (count/harga), toleransi 2% untuk desimal."""
    tolerance = float((rules.get("tolerance") or {}).get("approx") or 0.02)
    integral = float(value).is_integer()
    for candidate in pool:
        if integral and float(candidate).is_integer():
            if value == candidate:
                return True
            continue
        limit = max(abs(candidate) * tolerance, 0.01)
        if abs(value - candidate) <= limit:
            return True
    return False


DIFF_WORDS = ("naik", "turun", "selisih", "beda", "meningkat", "menurun", "bertambah",
              "berkurang", "kenaikan", "penurunan", "delta")


def _derived_close(value: float, references: set[float], rules: dict) -> bool:
    tolerance = float(
        ((rules.get("scoring") or {}).get("angka_salah") or {}).get(
            "derived_tolerance_pct", 5.0
        )
    ) / 100
    for reference in references:
        if abs(value - reference) <= max(abs(reference) * tolerance, 0.01):
            return True
    return False


def _derived_diffs(pool: list[float]) -> set[float]:
    values: set[float] = set()
    for left in pool:
        for right in pool:
            if left == right:
                continue
            values.add(round(abs(left - right), 6))
    return values


def validate_answer(question: dict, answer: str, results: list[dict], rules: dict) -> tuple[str, bool]:
    """Validator angka pasca-jawaban. Return (jawaban_final, diblokir).

    Ketat terhadap angka asing, tetapi menerima angka TURUNAN yang sah:
    sum/avg subset (5%), persen rasio, dan selisih (bila jawaban menyebut
    "naik/turun/selisih/..."). 0 selalu sah.
    """
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", answer or "")
    numbers = parse_numbers(text, rules)

    stats = latest_stats(results)
    if stats:
        wanted = expected_stat(question.get("q", ""))
        target = stats.get(wanted) if wanted else None
        if target is not None and numbers and not close_enough(float(target), numbers, rules):
            return BLOCKED_ANSWER, True

    if not numbers:
        return answer, False

    pool = numbers_in_results(results, rules)
    if not pool:
        return (BLOCKED_ANSWER, True) if any(v != 0 for v in numbers) else (answer, False)

    sums, avgs = _subset_stats(pool)
    derived: set[float] = set(sums) | set(avgs)
    lowered = text.lower()
    if "%" in text or "persen" in lowered:
        derived |= _derived_percentages(pool)
    if any(word in lowered for word in DIFF_WORDS):
        derived |= _derived_diffs(pool)

    for value in numbers:
        if value == 0:
            continue  # 0 (mis. count = 0) selalu sah
        if _matches_pool(value, pool, rules):
            continue
        if _derived_close(value, derived, rules):
            continue
        return BLOCKED_ANSWER, True
    return answer, False


def evaluate_tools(
    question_id: str,
    tool_names: list[str],
    arguments_list: list[dict],
    expected: dict,
    rules: dict,
) -> tuple[bool, bool]:
    """Tool & parameter dinilai dari SELURUH rantai tool, bukan hanya tool pertama."""
    if expected.get("tool") is None:
        # Penolakan / tool tidak tersedia: tool baca-saja tidak mengubah data -> LULUS.
        return True, True
    allowed = EXPECT_ALT.get(question_id, {expected["tool"]})
    tool_ok = any(name in allowed for name in tool_names)
    params_ok = any(
        params_match_rules(question_id, arguments, expected, rules)
        for arguments in arguments_list
    )
    return tool_ok, params_ok


def call_model(model: str, messages: list[dict], with_tools: bool = True) -> dict:
    cfg = MODELS[model]
    api_key = str(getattr(settings, cfg["key_attr"], "") or "").strip()
    if not api_key:
        raise RuntimeError(f"{cfg['key_attr']} tidak tersedia")
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    if with_tools:
        payload["tools"] = tools.TOOLS_SCHEMA
        payload["tool_choice"] = "auto"
    last_error = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    f"{cfg['base']}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"LLM gagal: {last_error}")


def usage_cost(model: str, data: dict) -> float:
    usage = data.get("usage") or {}
    prompt_price, completion_price = MODELS[model]["price"]
    return (
        int(usage.get("prompt_tokens") or 0) / 1000 * prompt_price
        + int(usage.get("completion_tokens") or 0) / 1000 * completion_price
    )


def run_once(model: str, question: dict, rules: dict) -> tuple[dict, float]:
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": question["q"]},
    ]
    if question.get("definition_system"):
        messages[0]["content"] += f"\n\nDEFINISI SISTEM: {question['definition_system']}"

    cost = 0.0
    tool_names: list[str] = []
    arguments_list: list[dict] = []
    results: list[dict] = []
    answer = ""
    started = time.perf_counter()

    for _ in range(MAX_ROUNDS):
        data = call_model(model, messages)
        cost += usage_cost(model, data)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            answer = (message.get("content") or "").strip()
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
                    "content": json.dumps(result, default=str)[:TOOL_CONTENT_CAP],
                }
            )
    else:
        data = call_model(model, messages, with_tools=False)
        cost += usage_cost(model, data)
        answer = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()

    expected = EXPECTED.get(question["id"], {"tool": None})
    tool_ok, params_ok = evaluate_tools(
        question["id"], tool_names, arguments_list, expected, rules
    )

    raw_answer = answer
    answer, blocked = validate_answer(question, answer, results, rules)

    gt_ok, gt_reason = check_ground_truth(question, answer, rules)
    bad = [] if blocked else wrong_numbers(answer, results, rules)

    row = {
        "id": question["id"],
        "category": question["category"],
        "tools": tool_names,
        "parameter": arguments_list[0] if arguments_list else {},
        "arguments": arguments_list,
        "answer": answer[:500],
        "answer_raw": raw_answer[:300],
        "validator_blocked": bool(blocked),
        "expected_tool": expected["tool"],
        "tool_ok": bool(tool_ok),
        "param_ok": bool(params_ok),
        "gt_ok": gt_ok,
        "gt_reason": gt_reason,
        "e2e": bool(tool_ok and params_ok and gt_ok),
        "angka_salah": bad,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "cost_usd": round(cost, 8),
    }
    return row, cost


def summarize(rows: list[dict], model: str, cost: float) -> dict:
    total = len(rows)
    scored = [r for r in rows if r["id"] not in EXCLUDED]
    lat = sorted(r["latency_ms"] for r in rows)

    def pct(value: int, denominator: int) -> float:
        return round(value / denominator * 100, 1) if denominator else 0.0

    return {
        "model": model,
        "total": total,
        "tool_pct": pct(sum(1 for r in rows if r["tool_ok"]), total),
        "param_pct": pct(sum(1 for r in rows if r["param_ok"]), total),
        "e2e_pct": pct(sum(1 for r in rows if r["e2e"]), total),
        "e2e_dari_18_pct": pct(sum(1 for r in scored if r["e2e"]), len(scored)),
        "angka_salah_pct": pct(sum(1 for r in rows if r["angka_salah"]), total),
        "validator_blocked_count": sum(1 for r in rows if r.get("validator_blocked")),
        "validator_blocked_pct": pct(
            sum(1 for r in rows if r.get("validator_blocked")), total
        ),
        "latensi_p50": lat[len(lat) // 2] if lat else 0,
        "latensi_p95": lat[int(len(lat) * 0.95) - 1] if lat else 0,
        "biaya_usd": round(cost, 8),
        "detail": rows,
    }


def run_model(model: str, questions: list[dict], rules: dict, repeats: int = 3) -> dict:
    global TOTAL_SPENT
    rows: list[dict] = []
    cost_total = 0.0
    aborted = False
    errors = 0
    for question in questions:
        for repeat in range(repeats):
            if TOTAL_SPENT > BUDGET_USD:
                aborted = True
                break
            try:
                row, cost = run_once(model, question, rules)
            except Exception as exc:  # noqa: BLE001 - jangan kehilangan hasil
                errors += 1
                print(f"{model} {question['id']}#{repeat + 1} ERROR {type(exc).__name__}: {exc}")
                if errors >= 3:
                    raise RuntimeError(f"model {model} gagal 3x: {exc}") from exc
                continue
            errors = 0
            TOTAL_SPENT += cost
            cost_total += cost
            row["repeat"] = repeat + 1
            rows.append(row)
            print(
                f"{model} {row['id']}#{repeat + 1} tool={int(row['tool_ok'])} "
                f"par={int(row['param_ok'])} gt={int(row['gt_ok'])} e2e={int(row['e2e'])} "
                f"salah={len(row['angka_salah'])} ${cost:.6f}"
            )
        if aborted:
            break
    summary = summarize(rows, model, cost_total)
    summary["aborted_budget"] = aborted
    return summary


def main() -> int:
    rules = load_rules()
    set_name = "tuning"
    if "--set" in sys.argv:
        set_name = sys.argv[sys.argv.index("--set") + 1]
    questions = [
        q
        for q in yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
        if q.get("set") == set_name
    ]
    if "--model" in sys.argv:
        chosen = sys.argv[sys.argv.index("--model") + 1].split(",")
    else:
        chosen = ["deepseek"]
    repeats = 3
    if "--repeats" in sys.argv:
        repeats = max(1, int(sys.argv[sys.argv.index("--repeats") + 1]))

    out: dict = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "set": set_name,
        "questions_total": len(questions),
    }
    total = 0.0
    for model in chosen:
        key = str(getattr(settings, MODELS[model]["key_attr"], "") or "").strip()
        if not key:
            out[model] = {"available": False, "reason": f"{MODELS[model]['key_attr']} kosong"}
            print(f"{model}: TIDAK TERSEDIA (kredensial kosong)")
            continue
        if model == "gemini" and not key.startswith("AIza"):
            out[model] = {
                "available": False,
                "reason": "kredensial Gemini bukan kunci Google (AIza...)",
            }
            print("gemini: TIDAK TERSEDIA (kredensial bukan kunci Google)")
            continue
        try:
            summary = run_model(model, questions, rules, repeats=repeats)
        except Exception as exc:  # noqa: BLE001
            out[model] = {"available": False, "reason": str(exc)[:200]}
            print(f"{model}: GAGAL ({exc})")
            continue
        out[model] = summary
        total += summary["biaya_usd"]

    out["total_cost_usd"] = round(total, 8)
    out["kumulatif_proyek_usd"] = round(PREVIOUS_USD + total, 8)
    (BASE / f"validation_results_{set_name}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for model in chosen:
        summary = out.get(model) or {}
        if summary.get("available") is False:
            print(f"{model}: n/a ({summary['reason']})")
            continue
        print(
            f"SUMMARY {model}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
            f"e2e={summary['e2e_pct']}% e2e18={summary['e2e_dari_18_pct']}% "
            f"salah={summary['angka_salah_pct']}% biaya=${summary['biaya_usd']:.6f}"
        )
    print(f"TOTAL ${total:.8f} kumulatif ${PREVIOUS_USD + total:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
