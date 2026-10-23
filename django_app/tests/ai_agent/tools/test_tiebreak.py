"""Test tie-break harga (demo-ready): harga DESC, kode ASC."""

from __future__ import annotations

import pytest

from integrations.ai_agent.tools import list_records


@pytest.mark.django_db
def test_sort_sale_price_tiebreak_code_asc():
    result = list_records.run("product", sort="-sale_price", limit=5)
    assert result.ok
    codes = [row["code"] for row in result.data["rows"]]
    prices = [float(row["sale_price"] or 0) for row in result.data["rows"]]
    # Harga tidak naik, dan untuk harga yang sama kode harus ASC.
    assert prices == sorted(prices, reverse=True)
    for index in range(len(prices) - 1):
        if prices[index] == prices[index + 1]:
            assert codes[index] < codes[index + 1]


@pytest.mark.django_db
def test_default_sort_produk_deterministik():
    first = list_records.run("product", limit=5).data["rows"]
    second = list_records.run("product", limit=5).data["rows"]
    assert [row["code"] for row in first] == [row["code"] for row in second]
