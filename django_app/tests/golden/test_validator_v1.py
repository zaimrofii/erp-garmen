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


# --- v2: angka turunan yang sah tidak boleh diblokir -------------------------

def _q(text: str = "Berapa hasilnya?") -> dict:
    return {"id": "T", "q": text}


def test_derived_sum_lulus():
    results = [{"ok": True, "rows": [{"value": 12}, {"value": 10}, {"value": 12}]}]
    answer, blocked = validate_answer(_q(), "total 34", results, RULES)
    assert blocked is False and answer == "total 34"


def test_derived_avg_lulus():
    results = [{"ok": True, "rows": [{"value": v} for v in (10, 50, 90)]}]
    answer, blocked = validate_answer(_q("Berapa rata-rata?"), "rata-rata 50", results, RULES)
    assert blocked is False


def test_derived_pct_lulus():
    results = [{"ok": True, "numerator": 25, "denominator": 100}]
    answer, blocked = validate_answer(_q(), "25%", results, RULES)
    assert blocked is False


def test_derived_diff_lulus():
    results = [{"ok": True, "rows": [{"value": 100}, {"value": 112}]}]
    answer, blocked = validate_answer(_q(), "naik 12", results, RULES)
    assert blocked is False


def test_tanpa_data_tanpa_angka_lulus():
    results = [{"ok": True, "stats": {"avg": None, "latest": None, "count": 0}}]
    answer, blocked = validate_answer(_q("Berapa scrap?"), "tidak ada data", results, RULES)
    assert blocked is False


def test_nol_adalah_count_yang_benar():
    results = [{"ok": True, "stats": {"avg": None, "latest": None, "count": 0}}]
    answer, blocked = validate_answer(_q("Berapa order?"), "0 order", results, RULES)
    assert blocked is False


def test_angka_asing_saat_nol_diblokir():
    results = [{"ok": True, "stats": {"avg": None, "latest": None, "count": 0}}]
    answer, blocked = validate_answer(_q("Berapa order?"), "12 order", results, RULES)
    assert blocked is True and answer == BLOCKED_ANSWER


def test_angka_tidak_cocok_apa_pun_diblokir():
    results = [{"ok": True, "rows": [{"value": v} for v in (10, 50, 90)]}]
    answer, blocked = validate_answer(_q(), "sekitar 40", results, RULES)
    assert blocked is True


def test_angka_besar_tidak_cocok_diblokir():
    results = [{"ok": True, "rows": [{"value": v} for v in (10, 50, 90)]}]
    answer, blocked = validate_answer(_q(), "300", results, RULES)
    assert blocked is True


def test_dua_angka_turunan_dan_row_count_lulus():
    results = [
        {"ok": True, "row_count": 3, "rows": [{"value": 12}, {"value": 10}, {"value": 12}]}
    ]
    answer, blocked = validate_answer(_q(), "34 dan 3", results, RULES)
    assert blocked is False


# --- v3: periode kosong (G028) ----------------------------------------------

def test_periode_kosong_angka_periode_lain_diblokir():
    results = [
        {
            "ok": True,
            "period": {"from": "2026-10-16", "to": "2026-10-23"},
            "stats": {"avg": None, "latest": None, "count": 0},
        }
    ]
    question = {"id": "G028", "q": "Berapa scrap minggu ini?"}
    answer, blocked = validate_answer(question, "262 order", results, RULES)
    assert blocked is True


def test_periode_kosong_jawaban_tidak_ada_data_lulus():
    results = [
        {
            "ok": True,
            "period": {"from": "2026-10-16", "to": "2026-10-23"},
            "stats": {"avg": None, "latest": None, "count": 0},
        }
    ]
    question = {"id": "G028", "q": "Berapa scrap minggu ini?"}
    answer, blocked = validate_answer(question, "tidak ada data", results, RULES)
    assert blocked is False

