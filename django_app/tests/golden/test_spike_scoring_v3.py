"""Test aturan skor Spike-3 (+ parser DSML). Tanpa LLM, tanpa DB.

Menjalankan aturan NYATA dari `spike_scoring_rules.md` supaya test dan runner
tidak bisa menyimpang.
"""

from __future__ import annotations

import pytest

from tests.golden.spike_runner_v3 import (
    load_rules,
    parse_dsml_calls,
    parse_numbers,
    strip_dsml,
    wrong_numbers,
)

RULES = load_rules()


def _results(*values: float) -> list[dict]:
    return [{"values": list(values)}]


# ---------------------------------------------------------------- parse angka
def test_parse_rupiah_indonesia():
    assert parse_numbers("Rp250.000,00", RULES) == [250000.0]


def test_parse_kode_dan_persen():
    assert parse_numbers("SEWING-2 dan 12,5%", RULES) == [12.5]


def test_parse_ribu():
    assert parse_numbers("250 ribu", RULES) == [250000.0]


def test_parse_tahun_diabaikan():
    assert parse_numbers("tahun 2026", RULES) == []


def test_parse_desimal_titik_tidak_jadi_ribuan():
    # "0.375" dari JSON Django = desimal, bukan 375.
    assert parse_numbers("lead time 0,375 jam (0.375)", RULES) == [0.375, 0.375]


def test_parse_rentang_tanggal_diabaikan():
    assert parse_numbers("periode 1–31 Januari 2026", RULES) == []
    assert parse_numbers("tanggal 19-25 Okt 2026", RULES) == []


# ------------------------------------------------------------- angka_salah
def test_angka_di_luar_hasil_tool_dianggap_salah():
    # 40 berada di antara 10 dan 90, tetapi range TIDAK lagi diizinkan.
    assert wrong_numbers("sekitar 40 unit", _results(10, 50, 90), RULES) == [40.0]


def test_angka_cocok_langsung():
    assert wrong_numbers("50 unit", _results(10, 50, 90), RULES) == []


def test_angka_derived_sum():
    assert wrong_numbers("totalnya 150", _results(10, 50, 90), RULES) == []
    assert wrong_numbers("150", _results(10, 50, 90), RULES) == []


def test_angka_derived_avg():
    # (10+50+90)/3 = 50
    assert wrong_numbers("rata-ratanya 50", _results(10, 50, 90), RULES) == []


def test_angka_tidak_derived_dianggap_salah():
    assert wrong_numbers("300", _results(10, 50, 90), RULES) == [300.0]


def test_persen_turunan_diterima():
    assert wrong_numbers("50%", _results(50), RULES) == []


def test_hasil_tool_kosong_boleh_tidak_ada_data():
    assert wrong_numbers("tidak ada data", [], RULES) == []


def test_hasil_tool_kosong_boleh_nol():
    assert wrong_numbers("0", [], RULES) == []


def test_hasil_tool_kosong_angka_lain_salah():
    assert wrong_numbers("17", [], RULES) == [17.0]


# ------------------------------------------------------------------- DSML
def test_dsml_json_valid_diekstrak():
    text = (
        "Penjelasan singkat. <｜｜DSML｜｜>"
        '{"name":"get_metric","arguments":{"name":"garment.wip"}}'
        "<｜｜/DSML｜｜>"
    )
    calls = parse_dsml_calls(text)
    assert calls == [{"name": "get_metric", "arguments": {"name": "garment.wip"}}]


def test_dsml_tanpa_json_tidak_crash():
    text = "<｜｜DSML｜｜> ini bukan json <｜｜/DSML｜｜>"
    assert parse_dsml_calls(text) == []
    assert strip_dsml(text) == "ini bukan json"


def test_dsml_tag_saja_dibersihkan():
    text = "<｜｜DSML｜｜><｜｜/DSML｜｜>"
    assert parse_dsml_calls(text) == []
    assert strip_dsml(text) == ""


def test_dsml_invoke_diekstrak():
    text = (
        '<｜｜DSML｜｜>calls> <｜｜DSML｜｜>invoke name="get_stock">'
        '<｜｜DSML｜｜>parameter name="product_code">ODOO-65</｜｜DSML｜｜>parameter>'
        "</｜｜DSML｜｜>invoke>"
    )
    calls = parse_dsml_calls(text)
    assert calls and calls[0]["name"] == "get_stock"
    assert calls[0]["arguments"].get("product_code") == "ODOO-65"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
