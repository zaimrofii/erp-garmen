"""Test validator angka produksi (Fase 1) — 18 kasus dari putaran spike."""

from __future__ import annotations

from integrations.ai_agent.agent.validator import (
    BLOCKED_ANSWER,
    guard_answer,
    validate_answer,
)

QUESTION_AVG = "Berapa rata-rata lead time minggu ini?"
STATS = {"ok": True, "data": {"stats": {"avg": 77.64, "latest": 191.86, "count": 2}}}


def _rows(*values: float) -> list[dict]:
    return [{"ok": True, "data": {"rows": [{"value": value} for value in values]}}]


def test_latest_bukan_avg_diblokir():
    answer, verdict = guard_answer("191,86 jam.", [STATS], QUESTION_AVG)
    assert verdict["ok"] is False and answer == BLOCKED_ANSWER


def test_angka_sesuai_avg_lulus():
    answer, verdict = guard_answer("77,64 jam.", [STATS], QUESTION_AVG)
    assert verdict["ok"] is True and answer == "77,64 jam."


def test_rata_rata_avg_lulus():
    answer, verdict = guard_answer("rata-rata 77,64 jam.", [STATS], QUESTION_AVG)
    assert verdict["ok"] is True


def test_tanpa_data_lulus():
    results = [{"ok": True, "data": {"stats": {"avg": None, "latest": None, "count": 0}}}]
    answer, verdict = guard_answer("Tidak ada data untuk periode itu.", results, "Berapa scrap?")
    assert verdict["ok"] is True


def test_mengarang_saat_tanpa_data_diblokir():
    results = [{"ok": True, "data": {"stats": {"avg": None, "latest": None, "count": 0}}}]
    answer, verdict = guard_answer("Ada 12 bundle scrap.", results, "Berapa scrap?")
    assert verdict["ok"] is False


def test_tanpa_stats_jawaban_teks_lulus():
    results = [{"ok": True, "data": {"rows": [{"code": "SO-1", "is_late": True}]}}]
    answer, verdict = guard_answer("Order SO-1 terlambat.", results, "Order mana yang terlambat?")
    assert verdict["ok"] is True


def test_derived_sum_lulus():
    answer, verdict = guard_answer("total 34", _rows(12, 10, 12))
    assert verdict["ok"] is True


def test_derived_avg_lulus():
    answer, verdict = guard_answer("rata-rata 50", _rows(10, 50, 90), "Berapa rata-rata?")
    assert verdict["ok"] is True


def test_derived_pct_lulus():
    results = [{"ok": True, "data": {"numerator": 25, "denominator": 100}}]
    answer, verdict = guard_answer("25%", results)
    assert verdict["ok"] is True


def test_derived_diff_lulus():
    answer, verdict = guard_answer("naik 12", _rows(100, 112))
    assert verdict["ok"] is True


def test_nol_adalah_count_yang_benar():
    results = [{"ok": True, "data": {"stats": {"avg": None, "latest": None, "count": 0}}}]
    answer, verdict = guard_answer("0 order", results, "Berapa order?")
    assert verdict["ok"] is True


def test_angka_asing_saat_nol_diblokir():
    results = [{"ok": True, "data": {"stats": {"avg": None, "latest": None, "count": 0}}}]
    answer, verdict = guard_answer("12 order", results, "Berapa order?")
    assert verdict["ok"] is False and answer == BLOCKED_ANSWER


def test_angka_tidak_cocok_apa_pun_diblokir():
    answer, verdict = guard_answer("sekitar 40", _rows(10, 50, 90))
    assert verdict["ok"] is False


def test_angka_besar_tidak_cocok_diblokir():
    answer, verdict = guard_answer("300", _rows(10, 50, 90))
    assert verdict["ok"] is False


def test_dua_angka_turunan_dan_row_count_lulus():
    results = [
        {
            "ok": True,
            "row_count": 3,
            "data": {"rows": [{"value": 12}, {"value": 10}, {"value": 12}]},
        }
    ]
    answer, verdict = guard_answer("34 dan 3", results)
    assert verdict["ok"] is True


def test_periode_kosong_angka_periode_lain_diblokir():
    results = [
        {
            "ok": True,
            "data": {
                "period": {"from": "2026-10-16", "to": "2026-10-23"},
                "stats": {"avg": None, "latest": None, "count": 0},
            },
        }
    ]
    answer, verdict = guard_answer("262 order", results, "Berapa scrap minggu ini?")
    assert verdict["ok"] is False


def test_periode_kosong_jawaban_tidak_ada_data_lulus():
    results = [
        {
            "ok": True,
            "data": {
                "period": {"from": "2026-10-16", "to": "2026-10-23"},
                "stats": {"avg": None, "latest": None, "count": 0},
            },
        }
    ]
    answer, verdict = guard_answer("tidak ada data", results, "Berapa scrap minggu ini?")
    assert verdict["ok"] is True


def test_penolakan_dengan_angka_tidak_diblokir():
    answer, verdict = guard_answer(
        "Maaf, saya tidak bisa menghapus order; saat ini ada 3 order aktif.", []
    )
    assert verdict["ok"] is True


def test_invalid_tanpa_tool_diblokir():
    # Perbaikan #1: tanpa tool, cek angka dilewati (jawaban naratif sah).
    verdict = validate_answer("Ada 5 order.", [])
    assert verdict["ok"] is True
    assert verdict["reason"] == "no_tool_called"
