"""Test perbaikan skor v5: parameter lintas-rantai tool + pertanyaan ber-`expected: null`."""

from __future__ import annotations

from tests.golden.spike_runner_v3 import load_rules
from tests.golden.validation_runner import BLOCKED_ANSWER, evaluate_tools, validate_answer

RULES = load_rules()
G001 = {"tool": "count_records", "must": ["bundle", "sewing-2"]}
NO_TOOL = {"tool": None}


def test_multiturn_parameter_dinilai_dari_seluruh_rantai():
    """tool[0] parameternya salah, tool[1] benar -> parameter LULUS."""
    tool_ok, params_ok = evaluate_tools(
        "G001",
        ["count_records", "list_records"],
        [{"entity": "order"}, {"entity": "bundle", "filters": {"work_center": "SEWING-2"}}],
        G001,
        RULES,
    )
    assert tool_ok is True
    assert params_ok is True


def test_multiturn_semua_parameter_salah_gagal():
    tool_ok, params_ok = evaluate_tools(
        "G001",
        ["count_records", "list_records"],
        [{"entity": "order"}, {"entity": "product"}],
        G001,
        RULES,
    )
    assert tool_ok is True
    assert params_ok is False


def test_penolakan_boleh_baca_dulu_lalu_menolak():
    """G014: panggil list_records (baca) lalu menolak -> LULUS."""
    tool_ok, params_ok = evaluate_tools(
        "G014", ["list_records"], [{"entity": "order"}], NO_TOOL, RULES
    )
    assert (tool_ok, params_ok) == (True, True)


def test_penolakan_tanpa_tool_tetap_lulus():
    tool_ok, params_ok = evaluate_tools("G012", [], [], NO_TOOL, RULES)
    assert (tool_ok, params_ok) == (True, True)


def test_g027_tool_kurang_tetap_lulus():
    """G027: tidak ada tool relasi -> model menyatakan tidak bisa dijawab -> LULUS."""
    tool_ok, params_ok = evaluate_tools("G027", [], [], NO_TOOL, RULES)
    assert (tool_ok, params_ok) == (True, True)


def test_tool_tidak_sesuai_expected_gagal():
    tool_ok, params_ok = evaluate_tools(
        "G001", ["get_metric"], [{"name": "garment.lead_time"}], G001, RULES
    )
    assert (tool_ok, params_ok) == (False, False)


def test_validator_memblokir_angka_di_luar_tool():
    question = {"id": "X1", "q": "Berapa total qty bundle?"}
    results = [{"ok": True, "count": 12}]
    answer, blocked = validate_answer(question, "Ada 99 bundle.", results, RULES)
    assert blocked is True
    assert answer == BLOCKED_ANSWER


def test_validator_meloloskan_angka_sesuai_tool():
    question = {"id": "X2", "q": "Berapa total qty bundle?"}
    results = [{"ok": True, "count": 12}]
    answer, blocked = validate_answer(question, "Ada 12 bundle.", results, RULES)
    assert blocked is False
    assert answer == "Ada 12 bundle."
