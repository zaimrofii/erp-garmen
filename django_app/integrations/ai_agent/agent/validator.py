"""Validator angka produksi (Fase 1).

Aturan (sama dengan spike v2 yang sudah dikunci):
  * Angka jawaban harus cocok dengan angka di hasil tool (integer exact,
    desimal toleransi 2%), ATAU
  * angka turunan yang sah: SUM/AVG subset (5%), persen rasio (bila jawaban
    memuat %/persen), selisih (bila jawaban memuat naik/turun/selisih/...), ATAU
  * nol (mis. count = 0).

Jawaban penolakan ("tidak bisa", "tidak ada", "maaf", "belum bisa diakses")
tidak diblokir meski memuat angka.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

BLOCKED_ANSWER = (
    "Angka yang dihasilkan tidak konsisten dengan data. Coba tanyakan lebih spesifik."
)

REFUSAL_WORDS = (
    "tidak bisa",
    "tidak dapat",
    "tidak ada",
    "maaf",
    "belum bisa diakses",
    "belum tersedia",
    "tidak tersedia",
    "tidak diizinkan",
)
DIFF_WORDS = (
    "naik",
    "turun",
    "selisih",
    "beda",
    "meningkat",
    "menurun",
    "bertambah",
    "berkurang",
    "kenaikan",
    "penurunan",
    "delta",
)
STAT_KEYS = ("avg", "latest", "min", "max", "count", "sum")
MONTHS = r"(?:jan|feb|mar|apr|mei|jun|jul|agu|sep|okt|nov|des)"
SCALE_WORDS = {"ribu": 1000.0, "rb": 1000.0, "juta": 1000000.0}
YEAR_LOW, YEAR_HIGH = 2000, 2100
TOLERANCE = 0.02
DERIVED_TOLERANCE = 0.05


def parse_numbers(text: str) -> list[float]:
    """Parser angka Indonesia: '1.234,56', '12,5%', '250 ribu'; kode/tanggal diabaikan."""
    text = re.sub(r"(?i)\brp\.?\s*", "Rp ", text or "")
    text = re.sub(
        r"\b(?=[A-Za-z][A-Za-z0-9/-]*\d)[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*\b",
        " ",
        text,
    )
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", text)
    text = re.sub(rf"\b\d{{1,2}}\s*[–-]\s*\d{{1,2}}\s*{MONTHS}\w*", " ", text, flags=re.I)
    text = re.sub(rf"\b\d{{1,2}}\s+{MONTHS}\w*(?:\s+\d{{4}})?\b", " ", text, flags=re.I)
    text = re.sub(r"(?<=\d)\s*[–-]\s*(?=\d)", " ", text)

    out: list[float] = []
    pattern = r"(?<![\w-])(\d[\d.,]*)\s*(ribu|rb|juta)?"
    for match in re.finditer(pattern, text):
        token = match.group(1).rstrip(".,")
        scale = (match.group(2) or "").lower()
        value = _to_float(token)
        if scale:
            value *= SCALE_WORDS.get(scale, 1.0)
        if not scale and float(value).is_integer() and YEAR_LOW <= int(value) <= YEAR_HIGH:
            continue  # tahun bukan angka data
        out.append(value)
    return out


def _to_float(token: str) -> float:
    if re.fullmatch(r"0\.\d+", token):
        return float(token)
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", token) and (
        token.count(",") >= 2 or "." in token
    ):
        return float(token.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", token):
        whole, _, frac = token.replace(".", "").partition(",")
        return float(f"{whole}.{frac}" if frac else whole)
    if re.fullmatch(r"\d+,\d+", token):
        return float(token.replace(",", "."))
    if re.fullmatch(r"\d+(\.\d+)?", token):
        return float(token)
    return float(re.sub(r"[.,]", "", token) or 0)


def numbers_in_results(tool_results: list[dict] | dict) -> list[float]:
    """Semua angka numerik di envelope/data hasil tool."""
    out: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
            return
        if isinstance(node, str):
            text = node.strip()
            if re.fullmatch(r"-?\d+(\.\d+)?", text):
                out.append(float(text))
            elif re.fullmatch(r"-?\d+(,\d+)?", text):
                out.append(float(text.replace(",", ".")))
            else:
                out.extend(parse_numbers(text))
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    items = tool_results if isinstance(tool_results, list) else [tool_results]
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            walk(item.get("data"))
            for extra in ("row_count", "truncated"):
                value = item.get(extra)
                if isinstance(value, (int, float)):
                    walk(value)
        else:
            walk(item)
    return out


def _close(value: float, reference: float, tolerance: float) -> bool:
    return abs(value - reference) <= max(abs(reference) * tolerance, 0.01)


def _subset_stats(pool: list[float]) -> tuple[set[float], set[float]]:
    sums: set[float] = set()
    avgs: set[float] = set()
    if len(pool) <= 10:
        for size in range(1, len(pool) + 1):
            for combo in combinations(range(len(pool)), size):
                values = [pool[index] for index in combo]
                sums.add(round(sum(values), 6))
                avgs.add(round(sum(values) / len(values), 6))
    else:
        sums.add(round(sum(pool), 6))
        for left, right in combinations(pool, 2):
            sums.add(round(left + right, 6))
            avgs.add(round((left + right) / 2, 6))
    return sums, avgs


def _percentages(pool: list[float]) -> set[float]:
    values: set[float] = set()
    for left in pool:
        for right in pool:
            if right == 0:
                continue
            values.add(round(left / right * 100, 6))
            values.add(round((left - right) / right * 100, 6))
    return values


def _diffs(pool: list[float]) -> set[float]:
    return {round(abs(left - right), 6) for left in pool for right in pool if left != right}


def _stats_of(tool_results: list[dict]) -> dict | None:
    for item in reversed(tool_results or []):
        data = item.get("data") if isinstance(item, dict) and "data" in item else item
        if isinstance(data, dict) and isinstance(data.get("stats"), dict):
            return data["stats"]
    return None


def expected_stat(question: str) -> str | None:
    text = (question or "").lower()
    if "rata-rata" in text or "rata rata" in text:
        return "avg"
    if "tertinggi" in text or "termahal" in text or "paling mahal" in text:
        return "max"
    if "terendah" in text or "termurah" in text or "paling murah" in text:
        return "min"
    if "terbaru" in text or "terakhir" in text:
        return "latest"
    return None


def _is_refusal(answer: str) -> bool:
    lowered = (answer or "").lower()
    return any(word in lowered for word in REFUSAL_WORDS)


def validate_answer(
    answer: str, tool_results: list[dict] | dict | None = None, question: str = ""
) -> dict:
    """Nilai konsistensi angka jawaban. Return {ok: bool, reason: str}."""
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", answer or "")
    numbers = parse_numbers(text)
    if not numbers:
        return {"ok": True, "reason": "no_numbers"}

    items = tool_results or []
    if isinstance(items, dict):
        items = [items]

    stats = _stats_of(items)
    if stats:
        field_name = expected_stat(question)
        target = stats.get(field_name) if field_name else None
        if target is not None and not any(
            _close(float(target), value, TOLERANCE) for value in numbers
        ):
            return {"ok": False, "reason": f"stats.{field_name} tidak cocok"}

    pool = numbers_in_results(items)
    if not pool:
        if all(value == 0 for value in numbers):
            return {"ok": True, "reason": "zero_only"}
        if _is_refusal(answer):
            return {"ok": True, "reason": "refusal"}
        return {"ok": False, "reason": "tidak ada angka di hasil tool"}

    sums, avgs = _subset_stats(pool)
    derived: set[float] = set(sums) | set(avgs)
    lowered = text.lower()
    if "%" in text or "persen" in lowered:
        derived |= _percentages(pool)
    if any(word in lowered for word in DIFF_WORDS):
        derived |= _diffs(pool)

    for value in numbers:
        if value == 0:
            continue
        if any(_close(value, candidate, TOLERANCE) for candidate in pool):
            continue
        if any(_close(value, candidate, DERIVED_TOLERANCE) for candidate in derived):
            continue
        if _is_refusal(answer):
            return {"ok": True, "reason": "refusal"}
        return {"ok": False, "reason": f"angka {value:g} tidak ada di hasil tool"}

    return {"ok": True, "reason": "match"}


def guard_answer(
    answer: str, tool_results: list[dict] | dict | None = None, question: str = ""
) -> tuple[str, dict]:
    """Return (jawaban_final, hasil_validasi); jawaban diganti bila tidak konsisten."""
    verdict = validate_answer(answer, tool_results, question)
    if verdict["ok"]:
        return answer, verdict
    return BLOCKED_ANSWER, verdict


__all__ = (
    "BLOCKED_ANSWER",
    "expected_stat",
    "guard_answer",
    "numbers_in_results",
    "parse_numbers",
    "validate_answer",
)

