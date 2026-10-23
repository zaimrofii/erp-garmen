"""Test get_stock mode top_n (Extension 3)."""

from __future__ import annotations

import pytest

from integrations.ai_agent.tools import get_stock


@pytest.mark.django_db
def test_top_n_envelope_dan_urutan():
    result = get_stock.run(mode="top_n", limit=5)
    assert result.ok, result.error
    assert result.data["mode"] == "top_n"
    rows = result.data["rows"]
    assert isinstance(rows, list) and len(rows) <= 5
    quantities = [row["quantity"] for row in rows]
    assert quantities == sorted(quantities, reverse=True)
    assert result.metadata["source"] == "Odoo"


@pytest.mark.django_db
def test_single_tanpa_kode_ditolak():
    with pytest.raises(ValueError):
        get_stock.run()
