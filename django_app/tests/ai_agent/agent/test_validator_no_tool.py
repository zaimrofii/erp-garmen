"""Test Perbaikan #1: validator tidak memblokir jawaban tanpa tool."""

from __future__ import annotations

from integrations.ai_agent.agent.validator import validate_answer


def test_tanpa_tool_jawaban_berangka_lulus():
    # "berapa 2+2" -> jawaban "4", tidak ada tool dipanggil.
    verdict = validate_answer("2 + 2 = 4.", [])
    assert verdict["ok"] is True
    assert verdict["reason"] == "no_tool_called"
    assert verdict["post_tool"] is False


def test_tanpa_tool_tapi_none_lulus():
    verdict = validate_answer("Sapi adalah hewan berkaki empat.", None)
    assert verdict["ok"] is True
    assert verdict["reason"] == "no_tool_called"


def test_dengan_tool_angka_di_data_lulus():
    results = [{"tool": "list_records", "row_count": 1, "result": {"harga_jual": 250000}}]
    verdict = validate_answer("Produk termahal Rp250.000.", results)
    assert verdict["ok"] is True


def test_dengan_tool_angka_di_luar_data_diblokir():
    results = [{"tool": "list_records", "row_count": 1, "result": {"harga_jual": 250000}}]
    verdict = validate_answer("Produk termahal Rp999.000.", results)
    assert verdict["ok"] is False
