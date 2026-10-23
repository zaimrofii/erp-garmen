"""Test aturan skor v4 (exact vs toleransi) + identifier G006. Tanpa LLM."""

from __future__ import annotations

from tests.golden.spike_runner_v3 import (
    check_ground_truth,
    load_rules,
    params_match_rules,
)

RULES = load_rules()


def _numeric(expected: list[float]) -> dict:
    return {"check": {"type": "numeric", "numbers": expected}}


def _approx(value: float) -> dict:
    return {"check": {"type": "numeric", "approx": value}}


def test_count_exact_lulus():
    assert check_ground_truth(_numeric([12]), "Ada 12 bundle.", RULES)[0] is True


def test_count_exact_gagal_selisih_satu():
    assert check_ground_truth(_numeric([12]), "Ada 13 bundle.", RULES)[0] is False


def test_harga_exact_lulus():
    assert check_ground_truth(_numeric([250000]), "Harganya Rp250.000.", RULES)[0] is True


def test_harga_exact_gagal_selisih_seribu():
    assert check_ground_truth(_numeric([250000]), "Harganya Rp249.999.", RULES)[0] is False


def test_persen_toleran_dua_persen_lulus():
    assert check_ground_truth(_approx(12.5), "Sekitar 12,6%.", RULES)[0] is True


def test_persen_toleran_gagal_di_luar_dua_persen():
    assert check_ground_truth(_approx(12.5), "Sekitar 13%.", RULES)[0] is False


def test_g006_kode_produk_diterima():
    assert (
        check_ground_truth(_numeric([30]), "Stok 30 unit dari ODOO-65.", RULES)[0] is True
    )


def test_g006_param_kode_atau_nama_setara():
    expected = {"must": ["kaos"]}
    assert params_match_rules("G006", {"product_code": "ODOO-65"}, expected, RULES) is True
    assert (
        params_match_rules(
            "G006", {"product_code": "Kaos Polos Cotton Combed 30s"}, expected, RULES
        )
        is True
    )


def test_g006_param_tidak_relevan_ditolak():
    expected = {"must": ["kaos"]}
    assert params_match_rules("G006", {"product_code": "FG-JKT-RICH"}, expected, RULES) is False
