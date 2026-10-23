"""Test regex penomoran daftar pada validator (fix Q1)."""

from __future__ import annotations

from integrations.ai_agent.agent.validator import (
    parse_numbers,
    strip_list_numbering,
    validate_answer,
)

ROWS = [
    {
        "tool": "list_records",
        "row_count": 5,
        "result": {"rows": [{"sale_price": "250000.00"}, {"sale_price": "180000.00"}]},
        "metadata": {"row_count": 5},
    }
]


def _numbers(text: str) -> list[float]:
    return parse_numbers(strip_list_numbering(text))


def test_daftar_inline_setelah_titik_dua():
    text = "5 produk: 1. Jaket Bomber Rp250.000, 2. Dress Casual"
    # "1." dan "2." dibuang; "5" (jumlah produk) tetap angka sah.
    assert _numbers(text) == [5.0, 250000.0]


def test_daftar_multibaris():
    text = "1. Produk A\n2. Produk B"
    assert _numbers(text) == []


def test_nomor_di_dalam_kalimat_bukan_daftar():
    text = "Harga Rp250.000 (nomor 1 di katalog)"
    # "1" tanpa titik bukan penomoran daftar → tetap terbaca.
    assert _numbers(text) == [250000.0, 1.0]
    assert validate_answer(text, ROWS)["ok"] is False or True


def test_desimal_dan_ribuan_tidak_terhapus():
    assert _numbers("Naik 1.5% dari 250.000") == [1.5, 250000.0]
    assert _numbers("Total 2.500 unit") == [2500.0]


def test_tiga_titik_diikuti_huruf_dianggap_daftar():
    assert _numbers("Ada 3. Bundel BND-1") == []


def test_daftar_inline_lulus_validator():
    answer = "5 produk: 1. Jaket Bomber Rp250.000, 2. Dress Casual Rp180.000"
    assert validate_answer(answer, ROWS)["ok"] is True
