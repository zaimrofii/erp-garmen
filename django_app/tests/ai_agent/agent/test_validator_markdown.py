"""Test regex markdown & tabel pada validator (fix Q9/Q11)."""

from __future__ import annotations

from integrations.ai_agent.agent.validator import parse_numbers, strip_list_numbering


def _numbers(text: str) -> list[float]:
    return parse_numbers(strip_list_numbering(text))


def test_nomor_daftar_diikuti_bold():
    assert _numbers("2. **Celana Jean China** — Rp180.000") == [180000.0]


def test_nomor_daftar_diikuti_italic():
    assert _numbers("1. *Italic product* Rp250.000") == [250000.0]


def test_indeks_baris_tabel():
    assert _numbers("| 1 | Jaket Bomber | 250000 |") == [250000.0]
    assert _numbers("| 2 | Dress Casual | 175000 |") == [175000.0]


def test_daftar_biasa_regresi():
    assert _numbers("1. Produk A") == []


def test_desimal_dan_ribuan_aman():
    assert _numbers("Harga 1.5% dari 250.000") == [1.5, 250000.0]
    assert _numbers("Total 2.500 unit") == [2500.0]
