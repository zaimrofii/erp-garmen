"""Test validator v2 (demo-ready): derived, prior-turn, nama tanpa angka."""

from __future__ import annotations

from integrations.ai_agent.agent.validator import BLOCKED_ANSWER, guard_answer, validate_answer


def _rows(*values: float) -> list[dict]:
    return [{"ok": True, "data": {"rows": [{"value": value} for value in values]}}]


def test_derived_sum_lulus():
    answer, verdict = guard_answer("total 150", _rows(10, 50, 90))
    assert verdict["ok"] is True


def test_derived_avg_lulus():
    answer, verdict = guard_answer("rata-rata 50", _rows(10, 50, 90), "Berapa rata-rata?")
    assert verdict["ok"] is True


def test_derived_diff_lulus():
    answer, verdict = guard_answer("naik 12", _rows(100, 112))
    assert verdict["ok"] is True


def test_angka_exact_lulus():
    answer, verdict = guard_answer("12", _rows(12))
    assert verdict["ok"] is True


def test_angka_exact_salah_diblokir():
    answer, verdict = guard_answer("13", _rows(12))
    assert verdict["ok"] is False and answer == BLOCKED_ANSWER


def test_prior_turn_lulus():
    prior = _rows(100, 200, 300)
    answer, verdict = guard_answer("200", [], prior_results=prior)
    assert verdict["ok"] is True


def test_nama_tanpa_angka_lulus():
    verdict = validate_answer("Dress Casual", _rows(175000, 250000))
    assert verdict["ok"] is True


def test_nomor_urut_daftar_bukan_angka_data():
    answer = "2. Dress Casual Wanita — Rp175.000"
    verdict = validate_answer(answer, _rows(250000, 180000, 175000))
    assert verdict["ok"] is True

