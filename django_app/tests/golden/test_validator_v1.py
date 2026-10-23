"""Test validator angka pasca-jawaban (Langkah 3b). Tanpa LLM."""

from __future__ import annotations

from tests.golden.spike_runner_v3 import load_rules
from tests.golden.validation_runner import BLOCKED_ANSWER, validate_answer

RULES = load_rules()
QUESTION = {"id": "X", "q": "Berapa rata-rata lead time minggu ini?"}
STATS = {"ok": True, "stats": {"avg": 77.64, "latest": 191.86, "count": 2}}


def test_latest_bukan_avg_diblokir():
    answer, blocked = validate_answer(QUESTION, "191,86 jam.", [STATS], RULES)
    assert blocked is True
    assert answer == BLOCKED_ANSWER


def test_angka_sesuai_avg_lulus():
    answer, blocked = validate_answer(QUESTION, "77,64 jam.", [STATS], RULES)
    assert blocked is False
    assert answer == "77,64 jam."


def test_rata_rata_avg_lulus():
    answer, blocked = validate_answer(QUESTION, "rata-rata 77,64 jam.", [STATS], RULES)
    assert blocked is False
    assert answer == "rata-rata 77,64 jam."


def test_tanpa_data_lulus():
    question = {"id": "Y", "q": "Berapa scrap minggu ini?"}
    results = [{"ok": True, "stats": {"avg": None, "latest": None, "count": 0}}]
    answer, blocked = validate_answer(question, "Tidak ada data untuk periode itu.", results, RULES)
    assert blocked is False
    assert answer == "Tidak ada data untuk periode itu."


def test_mengarang_saat_tanpa_data_diblokir():
    question = {"id": "Y", "q": "Berapa scrap minggu ini?"}
    results = [{"ok": True, "stats": {"avg": None, "latest": None, "count": 0}}]
    answer, blocked = validate_answer(question, "Ada 12 bundle scrap.", results, RULES)
    assert blocked is True
    assert answer == BLOCKED_ANSWER


def test_tanpa_stats_tidak_memblokir_jawaban_teks():
    question = {"id": "Z", "q": "Order mana yang terlambat?"}
    results = [{"ok": True, "rows": [{"code": "SO-1", "is_late": True}]}]
    answer, blocked = validate_answer(question, "Order SO-1 terlambat.", results, RULES)
    assert blocked is False
