"""Spike-3 runner — aturan skor dibaca dari `spike_scoring_rules.md`.

Semua logika parsing/skor mengikuti blok YAML di file aturan (anti-koreksi
post-hoc). Jalankan: docker exec -i garmen_django python tests/golden/spike_runner_v3.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
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
from tests.golden import spike_tools_v3 as tools  # noqa: E402

BUDGET_USD = 0.0097  # sisa kumulatif: 0.05 - 0.0370657 ≈ 0.0129; sisakan margin
TOTAL_SPENT = 0.0
MAX_TOKENS = 200
TOOL_CONTENT_CAP = 4000
MAX_ROUNDS_B = 2  # spesifikasi: ≤3; dipakai 2 demi budget $0.010

RULES_PATH = BASE / "spike_scoring_rules.md"

SYSTEM_PROMPT = """Kamu asisten MES garmen. Jawab Bahasa Indonesia dengan angka konkret.
ATURAN:
- Panggil tool untuk pertanyaan data; jangan mengarang angka.
- Jika pertanyaan punya lebih dari satu klausa (dipisah "dan", "lalu", koma), jawab SEMUA klausa.
- Jika diminta "rata-rata", hitung aggregate avg (bukan menampilkan daftar per hari).
- Read-only: jangan menyarankan/melakukan perubahan data.
- Sebut angka persis dari tool, dengan satuan."""

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


def load_rules() -> dict:
    """Ambil blok ```yaml dari spike_scoring_rules.md."""
    text = RULES_PATH.read_text(encoding="utf-8")
    match = re.search(r"```yaml\s*(.*?)```", text, re.S)
    if not match:
        raise SystemExit("Blok yaml aturan skor tidak ditemukan")
    rules = yaml.safe_load(match.group(1))
    if not isinstance(rules, dict):
        raise SystemExit("Aturan skor bukan mapping")
    return rules


def parse_numbers(text: str, rules: dict) -> list[float]:
    """Parser angka sesuai aturan (Indonesia, persen, ribu/juta, kode bukan angka)."""
    cfg = rules.get("parsing", {})
    year_bounds = cfg.get("ignore_years") or [2000, 2100]
    year_low, year_high = int(year_bounds[0]), int(year_bounds[-1])
    scales = cfg.get("scale_words") or {}
    thousand = cfg.get("thousand_separator", ".")
    decimal = cfg.get("decimal_separator", ",")
    text = re.sub(r"(?i)\brp\.?\s*", "Rp ", text or "")
    # Kode (SEWING-2, ODOO-65, S00004, SO-2026-0040) bukan angka.
    text = re.sub(
        r"\b(?=[A-Za-z][A-Za-z0-9/-]*\d)[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*\b",
        " ",
        text,
    )
    # Tanggal ISO / slash / naratif bukan angka.
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", text)
    # Rentang tanggal ("19–25 Okt 2026", "1-31 Januari") — sebelum naratif.
    text = re.sub(
        r"\b\d{1,2}\s*[–-]\s*\d{1,2}\s*(?:jan|feb|mar|apr|mei|jun|jul|agu|sep|okt|nov|des)\w*",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|mei|jun|jul|agu|sep|okt|nov|des)\w*(?:\s+\d{4})?\b",
        " ",
        text,
        flags=re.I,
    )
    # Rentang angka ("5-10 unit") → dua angka terpisah.
    text = re.sub(r"(?<=\d)\s*[–-]\s*(?=\d)", " ", text)

    out: list[float] = []
    pattern = r"(?<![\w-])(\d[\d.,]*)\s*(ribu|rb|juta)?"
    for match in re.finditer(pattern, text):
        token = match.group(1).rstrip(".,")
        scale_word = (match.group(2) or "").lower()
        if re.fullmatch(r"0\.\d+", token):
            # "0.375" = desimal (Django JSON memakai titik desimal), bukan 375.
            value = float(token)
        elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", token) and (
            token.count(",") >= 2 or "." in token
        ):
            # Ribuan gaya Inggris: "1,234.56" → 1234.56
            value = float(token.replace(",", ""))
        elif re.fullmatch(rf"\d{{1,3}}({re.escape(thousand)}\d{{3}})+({re.escape(decimal)}\d+)?", token):
            whole, _, frac = token.replace(thousand, "").partition(decimal)
            value = float(f"{whole}.{frac}" if frac else whole)
        elif re.fullmatch(rf"\d+{re.escape(decimal)}\d+", token):
            value = float(token.replace(decimal, "."))
        elif re.fullmatch(r"\d+(\.\d+)?", token):
            value = float(token)
        else:
            value = float(re.sub(r"[.,]", "", token) or 0)
        if scale_word:
            value *= float(scales.get(scale_word, 1))
        if (
            not scale_word
            and float(value) == int(value)
            and year_low <= int(value) <= year_high
        ):
            continue
        out.append(value)
    return out


def check_ground_truth(question: dict, answer: str, rules: dict) -> tuple[bool, str]:
    """Cocokkan jawaban dengan `check` di YAML (numeric/entity/refuse/no_data)."""
    check = question.get("check") or {}
    kind = check.get("type")
    low = (answer or "").lower()
    numbers = parse_numbers(answer, rules)

    if kind in {"refuse", "no_data"}:
        hit = any(word.lower() in low for word in check.get("words", []))
        return hit, "penanda penolakan/data kosong" if hit else "tidak menolak"

    reasons: list[str] = []
    entities = check.get("entities") or []
    if entities and not any(entity.lower() in low for entity in entities):
        reasons.append("entity tidak muncul")
    for expected in check.get("numbers") or []:
        if not any(abs(value - expected) <= 0.5 for value in numbers):
            reasons.append(f"angka {expected} tidak ada")
    if "approx" in check:
        tolerance = float(check.get("tol", 0.5))
        if not any(abs(value - check["approx"]) <= tolerance for value in numbers):
            reasons.append(f"~{check['approx']} tidak ada")
    return (not reasons), (", ".join(reasons) or "cocok")


def numbers_in_results(results, rules: dict | None = None) -> list[float]:
    """Ambil angka dari struktur hasil tool (JSON) tanpa ambiguitas teks.

    Angka JSON (int/float) dipakai apa adanya — jadi 0.375 tetap 0.375, bukan
    375 seperti bila diperlakukan sebagai format ribuan Indonesia.
    """
    rules = rules or load_rules()
    out: list[float] = []

    def walk(node) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
            return
        if isinstance(node, str):
            text = node.strip()
            if re.fullmatch(r"-?\d+(\.\d+)?", text):
                out.append(float(text))
            else:
                out.extend(parse_numbers(text, rules))
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(results)
    return out


def _close(value: float, reference: float, tolerance: float) -> bool:
    return abs(value - reference) <= max(abs(reference) * tolerance, 0.01)


def _subset_stats(pool: list[float]) -> tuple[set[float], set[float]]:
    """Semua SUM & AVG subset (maks 10 angka) + total/pairwise untuk pool besar."""
    from itertools import combinations

    sums: set[float] = set()
    avgs: set[float] = set()
    if len(pool) <= 10:
        indices = range(len(pool))
        for size in range(1, len(pool) + 1):
            for combo in combinations(indices, size):
                values = [pool[i] for i in combo]
                sums.add(round(sum(values), 6))
                avgs.add(round(sum(values) / len(values), 6))
    else:
        sums.add(round(sum(pool), 6))
        for left, right in combinations(pool, 2):
            sums.add(round(left + right, 6))
            avgs.add(round((left + right) / 2, 6))
    return sums, avgs


def _derived_percentages(pool: list[float]) -> set[float]:
    """Persen turunan: rasio a/b*100 dan perubahan (a-b)/b*100."""
    values: set[float] = set()
    for left in pool:
        for right in pool:
            if right == 0:
                continue
            values.add(round(left / right * 100, 6))
            values.add(round((left - right) / right * 100, 6))
    return values


def wrong_numbers(answer: str, results: list[dict], rules: dict) -> list[float]:
    """Angka jawaban yang tidak sah menurut blok `angka_salah` di aturan."""
    cfg = (rules.get("scoring") or {}).get("angka_salah") or {}
    tolerance = float(cfg.get("tolerance_pct", 2.0)) / 100
    derived_tolerance = float(cfg.get("derived_tolerance_pct", 5.0)) / 100

    answered = parse_numbers(answer, rules)
    if not answered:
        return []
    pool = numbers_in_results(results, rules)

    if not pool:
        # (iii) hanya NOL yang sah bila tool tidak mengembalikan angka.
        return [value for value in answered if value != 0]

    sums, avgs = _subset_stats(pool)
    percentages = _derived_percentages(pool)
    must_match = bool(cfg.get("must_match_tool_output", True))

    bad: list[float] = []
    for value in answered:
        if value == 0:
            continue
        if any(_close(value, reference, tolerance) for reference in pool):
            continue
        if cfg.get("allow_derived_sum") and any(
            _close(value, reference, derived_tolerance) for reference in sums
        ):
            continue
        if cfg.get("allow_derived_avg") and any(
            _close(value, reference, derived_tolerance) for reference in avgs
        ):
            continue
        if cfg.get("allow_derived_pct") and any(
            _close(value, reference, derived_tolerance) for reference in percentages
        ):
            continue
        if not must_match:
            continue
        bad.append(value)
    return bad


DSML_TAG = re.compile(r"<｜｜[^｜]*｜｜>")
DSML_INVOKE = re.compile(r'invoke\s+name="([^"]+)"')
DSML_PARAM = re.compile(r'parameter\s+name="([^"]+)"[^>]*>([^<]*)</')


def strip_dsml(text: str) -> str:
    """Buang markup khusus DeepSeek agar jawaban bisa dinilai."""
    return DSML_TAG.sub("", text or "").strip()


def parse_dsml_calls(text: str) -> list[dict]:
    """Ekstrak tool-call dari markup `<｜｜DSML｜｜>` (JSON atau atribut invoke)."""
    body = strip_dsml(text)
    calls: list[dict] = []

    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = body.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(body[start:])
        except ValueError:
            index = start + 1
            continue
        if isinstance(obj, dict) and obj.get("name"):
            arguments = obj.get("arguments") or obj.get("parameters") or {}
            calls.append(
                {
                    "name": str(obj["name"]),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                }
            )
        index = start + end
    if calls:
        return calls

    for match in DSML_INVOKE.finditer(body):
        tail = body[match.end():]
        arguments = {pm.group(1): pm.group(2).strip() for pm in DSML_PARAM.finditer(tail)}
        calls.append({"name": match.group(1), "arguments": arguments})
    return calls


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


def run_question(question: dict, scenario: str, rules: dict) -> tuple[dict, float]:
    """Satu pertanyaan; definisi sistem (P1) dikirim ke prompt."""
    scoring = rules.get("scoring", {})
    expected = EXPECTED.get(question["id"], {"tool": None})
    max_rounds = 1 if scenario == "A" else MAX_ROUNDS_B

    system = SYSTEM_PROMPT
    definition = question.get("definition_system")
    if definition:
        system = f"{system}\n\nDEFINISI SISTEM: {definition}"

    messages = [
        {"role": "system", "content": system},
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
    dsml_unparseable = 0

    for _ in range(max_rounds):
        data = call_llm(messages, with_tools=True)
        cost += usage_cost(data)
        usage = data.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        if not calls and "｜｜" in content:
            parsed_calls = parse_dsml_calls(content)
            if parsed_calls:
                calls = [
                    {
                        "id": f"dsml_{index}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                        },
                    }
                    for index, call in enumerate(parsed_calls)
                ]
                message = {"role": "assistant", "content": "", "tool_calls": calls}
                print(f"{question['id']} DSML_RECOVERED {[c['name'] for c in parsed_calls]}")
            else:
                dsml_unparseable += 1
                print(f"{question['id']} dsml_unparseable")
        if not calls:
            answer = strip_dsml(content)
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
        data = call_llm(messages, with_tools=False)
        cost += usage_cost(data)
        usage = data.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        answer = strip_dsml(
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )

    refusal_ids = set(scoring.get("refusal_ids") or [])
    excluded = set(scoring.get("excluded_from_e2e") or [])
    alternatives = scoring.get("tool_alternatives", {}) or {}
    first_args = arguments_list[0] if arguments_list else {}
    expected_tool = expected.get("tool")

    if question["id"] in refusal_ids:
        tool_ok, params_ok = True, True
    else:
        allowed = set(
            alternatives.get(question["id"], [expected_tool] if expected_tool else [])
        )
        if allowed:
            if scenario == "A":
                tool_ok = bool(tool_names) and tool_names[0] in allowed
            else:
                tool_ok = any(name in allowed for name in tool_names)
            params_ok = params_match(first_args, expected.get("must", []))
        else:
            tool_ok, params_ok = (not tool_names), (not tool_names)

    gt_ok, gt_reason = check_ground_truth(question, answer, rules)
    bad = wrong_numbers(answer, results, rules)

    row = {
        "id": question["id"],
        "q": question["q"],
        "category": question["category"],
        "scenario": scenario,
        "expected_tool": expected_tool,
        "tools_dipilih": tool_names,
        "parameter": first_args,
        "tool_errors": [r.get("error") for r in results if r.get("error")],
        "answer": answer[:600],
        "ground_truth": question["ground_truth"],
        "cocok_ground_truth": gt_ok,
        "gt_reason": gt_reason,
        "tool_selection_benar": bool(tool_ok),
        "parameter_benar": bool(params_ok),
        "e2e_benar": bool(tool_ok and params_ok and gt_ok),
        "excluded_from_e2e": question["id"] in excluded,
        "angka_salah": bad,
        "angka_salah_count": len(bad),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tool_calls": len(tool_names),
        "dsml_unparseable": dsml_unparseable,
        "cost_usd": round(cost, 8),
    }
    return row, cost


def summarize(rows: list[dict], scenario: str, cost: float, rules: dict) -> dict:
    scoring = rules.get("scoring", {})
    excluded = set(scoring.get("excluded_from_e2e") or [])
    scored_rows = [r for r in rows if r["id"] not in excluded]
    total = len(rows)
    tool_ok = sum(1 for r in rows if r["tool_selection_benar"])
    param_ok = sum(1 for r in rows if r["parameter_benar"])
    e2e_scored = sum(1 for r in scored_rows if r["e2e_benar"])
    e2e_all = sum(1 for r in rows if r["e2e_benar"])
    wrong = sum(1 for r in rows if r["angka_salah_count"] > 0)

    per_category: dict[str, dict] = {}
    for row in rows:
        bucket = per_category.setdefault(
            row["category"], {"total": 0, "tool": 0, "param": 0, "e2e": 0, "wrong": 0}
        )
        bucket["total"] += 1
        bucket["tool"] += int(row["tool_selection_benar"])
        bucket["param"] += int(row["parameter_benar"])
        bucket["e2e"] += int(row["e2e_benar"])
        bucket["wrong"] += int(row["angka_salah_count"] > 0)

    return {
        "scenario": scenario,
        "total": total,
        "tool_pct": round(tool_ok / total * 100, 1) if total else 0.0,
        "param_pct": round(param_ok / total * 100, 1) if total else 0.0,
        "e2e_dari_13_pct": round(e2e_scored / len(scored_rows) * 100, 1) if scored_rows else 0.0,
        "e2e_dari_15_pct": round(e2e_all / total * 100, 1) if total else 0.0,
        "angka_salah_pct": round(wrong / total * 100, 1) if total else 0.0,
        "benar_e2e_13": e2e_scored,
        "benar_e2e_15": e2e_all,
        "denominator_13": len(scored_rows),
        "biaya_usd": round(cost, 8),
        "per_kategori": per_category,
        "detail": rows,
    }


def smoke_test(rules: dict, questions: list[dict]) -> float:
    """Verifikasi parser + skor pada G005 sebelum run penuh."""
    assert parse_numbers("Rp250.000,00", rules) == [250000.0], "parser ribuan gagal"
    assert parse_numbers("SEWING-2 dan 12,5%", rules) == [12.5], "parser kode/persen gagal"
    assert parse_numbers("250 ribu", rules) == [250000.0], "parser ribu gagal"

    question = next(q for q in questions if q["id"] == "G005")
    row, cost = run_question(question, "A", rules)
    print(
        f"SMOKE G005 e2e={row['e2e_benar']} gt={row['cocok_ground_truth']} "
        f"reason={row['gt_reason']} cost=${cost:.6f}"
    )
    print(f"SMOKE answer: {row['answer'][:120]}")
    return cost


def run_scenario(scenario: str, questions: list[dict], rules: dict) -> tuple[dict, float]:
    global TOTAL_SPENT
    rows: list[dict] = []
    cost_total = 0.0
    aborted = False
    for question in questions:
        if TOTAL_SPENT > BUDGET_USD:
            aborted = True
            print(f"ABORT skenario {scenario}: kumulatif ${TOTAL_SPENT:.6f} > ${BUDGET_USD}")
            break
        try:
            row, cost = run_question(question, scenario, rules)
        except Exception as exc:  # noqa: BLE001
            print(f"{scenario} {question['id']} ERROR {type(exc).__name__}: {exc}")
            continue
        TOTAL_SPENT += cost
        cost_total += cost
        rows.append(row)
        print(
            f"{scenario} {row['id']} tools={','.join(row['tools_dipilih'][:2]) or '-':34s} "
            f"tool={int(row['tool_selection_benar'])} par={int(row['parameter_benar'])} "
            f"gt={int(row['cocok_ground_truth'])} e2e={int(row['e2e_benar'])} "
            f"salah={row['angka_salah_count']} ${row['cost_usd']:.6f}"
        )
    summary = summarize(rows, scenario, cost_total, rules)
    summary["aborted_budget"] = aborted
    return summary, cost_total


def _arg(name: str, default: str | None = None) -> str | None:
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def merge_outputs() -> int:
    """Gabungkan hasil dua proses (A dan B) menjadi satu payload final."""
    path_a = BASE / "spike_results_v3_runA.json"
    path_b = BASE / "spike_results_v3_runB.json"
    if not path_a.exists() or not path_b.exists():
        raise SystemExit("File runA/runB belum ada; jalankan kedua skenario dulu")
    data_a = json.loads(path_a.read_text(encoding="utf-8"))
    data_b = json.loads(path_b.read_text(encoding="utf-8"))
    cost_a = float(data_a.get("total_cost_usd") or 0)
    cost_b = float(data_b.get("total_cost_usd") or 0)
    payload = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "model": data_a.get("model"),
        "rules_file": "tests/golden/spike_scoring_rules.md",
        "runs_used": 1,
        "budget_usd": 0.015,
        "total_cost_usd": round(cost_a + cost_b, 8),
        "kumulatif_proyek_usd": round(0.04651276 + cost_a + cost_b, 8),
        "tools": data_a.get("tools"),
        "skenario_A": data_a["skenario_A"],
        "skenario_B": data_b["skenario_B"],
    }
    out = BASE / "spike_results_v3.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for name in ("A", "B"):
        summary = payload[f"skenario_{name}"]
        print(
            f"SKENARIO {name}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
            f"e2e13={summary['e2e_dari_13_pct']}% e2e15={summary['e2e_dari_15_pct']}% "
            f"salah={summary['angka_salah_pct']}% biaya=${summary['biaya_usd']:.6f}"
        )
    print(
        f"TOTAL ${cost_a + cost_b:.8f} kumulatif ${0.04651276 + cost_a + cost_b:.8f} -> {out}"
    )
    return 0


def main() -> int:
    rules = load_rules()
    questions = yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
    model_label = str(getattr(settings, "AI_LLM_MODEL", "") or "deepseek-chat")

    if "--merge" in sys.argv:
        return merge_outputs()

    global BUDGET_USD, TOTAL_SPENT
    BUDGET_USD = float(_arg("--budget", str(BUDGET_USD)) or BUDGET_USD)
    scenario = str(_arg("--scenario", "both") or "both").upper()
    out_name = str(_arg("--out", "spike_results_v3.json") or "spike_results_v3.json")

    spent_smoke = 0.0
    if "--no-smoke" in sys.argv:
        print("SMOKE skipped (parser sudah diverifikasi pra-run)")
    else:
        spent_smoke = smoke_test(rules, questions)
    TOTAL_SPENT = spent_smoke

    summary_a = summary_b = None
    cost_a = cost_b = 0.0

    if scenario in {"A", "BOTH"}:
        summary_a, cost_a = run_scenario("A", questions, rules)

    if scenario in {"B", "BOTH"}:
        if scenario == "BOTH":
            estimate_b = max(cost_a * 1.9, 0.006)
            if TOTAL_SPENT + estimate_b > BUDGET_USD:
                print(
                    f"NOT_ENOUGH_BUDGET_FOR_B: spent ${TOTAL_SPENT:.6f}, "
                    f"estimasi B ${estimate_b:.6f}, cap ${BUDGET_USD}"
                )
            else:
                summary_b, cost_b = run_scenario("B", questions, rules)
        else:
            summary_b, cost_b = run_scenario("B", questions, rules)

    total_cost = round(cost_a + cost_b + spent_smoke, 8)
    payload = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "model": model_label,
        "rules_file": "tests/golden/spike_scoring_rules.md",
        "runs_used": 1,
        "budget_usd": BUDGET_USD,
        "smoke_cost_usd": round(spent_smoke, 8),
        "total_cost_usd": total_cost,
        "kumulatif_proyek_usd": round(0.04651276 + total_cost, 8),
        "tools": [t["function"]["name"] for t in tools.TOOLS_SCHEMA],
        "skenario_A": summary_a,
        "skenario_B": summary_b,
    }
    out = BASE / out_name
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    for name, summary in (("A", summary_a), ("B", summary_b)):
        if summary is None:
            print(f"SKENARIO {name}: TIDAK DIJALANKAN")
            continue
        print(
            f"SKENARIO {name}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
            f"e2e13={summary['e2e_dari_13_pct']}% e2e15={summary['e2e_dari_15_pct']}% "
            f"salah={summary['angka_salah_pct']}% biaya=${summary['biaya_usd']:.6f}"
        )
    print(
        f"TOTAL ${total_cost:.8f} kumulatif ${0.04651276 + total_cost:.8f} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

