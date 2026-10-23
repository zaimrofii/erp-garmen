"""Test validator deterministik (demo-ready)."""

from __future__ import annotations

import random

from integrations.ai_agent.agent.validator import validate_answer

STATS_BIG = [
    {"as_of": "2026-10-23T10:00:00", "data": {"stats": {"avg": 17.0, "count": 3}}},
    {"as_of": "2026-10-23T09:00:00", "data": {"rows": [{"value": 10}, {"value": 20}]}},
]


def test_input_sama_output_sama_10_kali():
    results = [validate_answer("17", STATS_BIG) for _ in range(10)]
    assert len({(r["ok"], r["reason"]) for r in results}) == 1
    assert results[0]["ok"] is True


def test_urutan_diacak_tetap_sama():
    expected = validate_answer("30", STATS_BIG)
    shuffled = list(STATS_BIG)
    for _ in range(5):
        random.shuffle(shuffled)
        verdict = validate_answer("30", shuffled)
        assert (verdict["ok"], verdict["reason"]) == (expected["ok"], expected["reason"])


def test_avg_cocok_lulus():
    assert validate_answer("17", [{"data": {"stats": {"avg": 17.0}}}])["ok"] is True


def test_avg_tidak_cocok_diblokir():
    assert validate_answer("17", [{"data": {"stats": {"avg": 16.0}}}])["ok"] is False
