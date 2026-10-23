"""40+ test case parser `parse_numbers` (tanpa LLM).

Satu assertion per test. Aturan skor tidak diubah; hanya parser yang boleh
diperbaiki bila test gagal.
"""

from __future__ import annotations

import pytest

from tests.golden.spike_runner_v3 import load_rules, numbers_in_results, parse_numbers

RULES = load_rules()


def nums(text: str) -> list[float]:
    return parse_numbers(text, RULES)


# A. Angka Indonesia -----------------------------------------------------------
def test_a1_rupiah_dengan_sen():
    assert nums("Rp250.000,00") == [250000.0]


def test_a2_jutaan_dengan_sen():
    assert nums("1.234.567,89") == [1234567.89]


def test_a3_rupiah_tanpa_sen():
    assert nums("Rp 250.000") == [250000.0]


def test_a4_ribuan_desimal():
    assert nums("12.500,5") == [12500.5]


def test_a5_desimal_koma():
    assert nums("0,5") == [0.5]


# B. Angka JSON/Inggris -------------------------------------------------------
def test_b6_desimal_titik_tiga_digit():
    assert nums("0.375") == [0.375]


def test_b7_desimal_titik_satu_digit():
    assert nums("0.5") == [0.5]


def test_b8_desimal_pi():
    assert nums("3.14") == [3.14]


def test_b9_ribuan_inggris_dengan_desimal():
    assert nums("1,234.56") == [1234.56]


def test_b10_desimal_kecil():
    assert nums("0.001") == [0.001]


# C. Persen -------------------------------------------------------------------
def test_c11_persen_koma():
    assert nums("12,5%") == [12.5]


def test_c12_persen_bulat():
    assert nums("25%") == [25.0]


def test_c13_persen_desimal_json():
    assert nums("0.375%") == [0.375]


def test_c14_persen_tiga_tujuh_lima():
    assert nums("37,5%") == [37.5]


def test_c15_persen_seratus():
    assert nums("100%") == [100.0]


# D. Rentang & tanggal --------------------------------------------------------
def test_d16_rentang_tanggal_bulan():
    assert nums("1–31 Januari") == []


def test_d17_rentang_tahun():
    assert nums("2020-2024") == []


def test_d18_rentang_angka_biasa():
    assert nums("5-10 unit") == [5.0, 10.0]


def test_d19_tanggal_iso():
    assert nums("2026-10-22") == []


def test_d20_tanggal_slash():
    assert nums("22/10/2026") == []


def test_d21_tanggal_naratif():
    assert nums("22 Oktober 2026") == []


# E. Kode ---------------------------------------------------------------------
def test_e22_kode_work_center():
    assert nums("SEWING-2") == []


def test_e23_kode_produk():
    assert nums("ODOO-65") == []


def test_e24_kode_order_odoo():
    assert nums("S00004") == []


def test_e25_kode_order_mes():
    assert nums("SO-2026-0040") == []


def test_e26_kode_qc():
    assert nums("QC-1") == []


# F. Skala kata ---------------------------------------------------------------
def test_f27_ribu():
    assert nums("250 ribu") == [250000.0]


def test_f28_juta_desimal_koma():
    assert nums("1,5 juta") == [1500000.0]


def test_f29_rb():
    assert nums("2 rb") == [2000.0]


def test_f30_juta_rupiah():
    assert nums("10 juta rupiah") == [10000000.0]


# G. Tahun --------------------------------------------------------------------
def test_g31_tahun_kata():
    assert nums("tahun 2026") == []


def test_g32_tahun_saja():
    assert nums("2026") == []


def test_g33_tahun_batas_bawah():
    assert nums("2020") == []


def test_g34_tahun_batas_atas():
    assert nums("2100") == []


def test_g35_sebelum_rentang_tahun_dihitung():
    assert nums("1999") == [1999.0]


def test_g36_setelah_rentang_tahun_dihitung():
    assert nums("2101") == [2101.0]


# H. Campuran -----------------------------------------------------------------
def test_h37_kalimat_total_dan_rata_rata():
    assert nums("total 1.234.567,89 dari 3 order, rata-rata 411.522,63") == [
        1234567.89,
        3.0,
        411522.63,
    ]


def test_h38_scrap_kode():
    assert nums("scrap 12,5% di SEWING-2") == [12.5]


def test_h39_rupiah_dan_persen():
    assert nums("Rp250.000,00 (naik 12%)") == [250000.0, 12.0]


def test_h40_desimal_dan_persen():
    assert nums("0.375 dari 100%") == [0.375, 100.0]


def test_h41_bundle_unit_jam():
    assert nums("3 bundle, total 30 unit, 0.5 jam") == [3.0, 30.0, 0.5]


# I. Kosong -------------------------------------------------------------------
def test_i42_string_kosong():
    assert nums("") == []


def test_i43_tidak_ada_data():
    assert nums("tidak ada data") == []


# J. Pool angka dari hasil tool (bukan regex jawaban) --------------------------
def test_j44_pool_json_memakai_desimal_titik():
    assert numbers_in_results([{"value": 0.375}]) == [0.375]


def test_j45_pool_json_string_indonesia():
    assert numbers_in_results([{"value": "250.000,00"}]) == [250000.0]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
