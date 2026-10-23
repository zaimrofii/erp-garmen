"""Test 2 tool baru (Langkah 2): aggregate_operator & get_product_orders. Tanpa LLM."""

from __future__ import annotations

import pytest

from tests.golden import spike_tools_v4 as T
from tests.golden.spike_tools_v4 import TOOLS_SCHEMA


def _tool(name: str) -> dict:
    return next(t for t in TOOLS_SCHEMA if t["function"]["name"] == name)


def test_schema_berisi_sembilan_tool():
    names = {t["function"]["name"] for t in TOOLS_SCHEMA}
    assert len(names) == 9
    assert {"aggregate_operator", "get_product_orders"} <= names


def test_schema_aggregate_operator_punya_date_dan_enum():
    props = _tool("aggregate_operator")["function"]["parameters"]["properties"]
    assert {"field", "op", "date_from", "date_to", "limit"} <= set(props)
    assert set(props["field"]["enum"]) == {"event_count", "output_qty"}
    assert set(props["op"]["enum"]) == {"sum", "count"}


def test_schema_get_product_orders_punya_product_code():
    params = _tool("get_product_orders")["function"]["parameters"]
    assert "product_code" in params["properties"]
    assert params["required"] == ["product_code"]


@pytest.mark.django_db
def test_aggregate_operator_envelope():
    result = T.execute("aggregate_operator", {"field": "output_qty", "op": "sum"})
    assert result["ok"] is True, result
    assert {"rows", "row_count", "period", "warnings"} <= set(result)
    assert isinstance(result["rows"], list)
    assert isinstance(result["row_count"], int)
    assert result["period"] == {"from": None, "to": None}


@pytest.mark.django_db
def test_aggregate_operator_filter_tanggal_tercatat_di_period():
    result = T.execute(
        "aggregate_operator",
        {
            "field": "event_count",
            "op": "count",
            "date_from": "2026-10-01",
            "date_to": "2026-10-23",
        },
    )
    assert result["ok"] is True, result
    assert result["period"] == {"from": "2026-10-01", "to": "2026-10-23"}
    # Tanpa data di periode itu, envelope tetap lengkap + warning eksplisit.
    assert isinstance(result["warnings"], list)


@pytest.mark.django_db
def test_aggregate_operator_field_tidak_didukung():
    result = T.execute("aggregate_operator", {"field": "gaji", "op": "sum"})
    assert result["ok"] is True and result.get("error") == "field_not_supported"


@pytest.mark.django_db
def test_get_product_orders_envelope_produk_tidak_ada():
    result = T.execute("get_product_orders", {"product_code": "TIDAK-ADA-XYZ"})
    assert result["ok"] is True, result
    assert {"product", "orders", "row_count", "warnings"} <= set(result)
    assert result["orders"] == [] and result["row_count"] == 0
    assert "product_not_found" in result["warnings"]


@pytest.mark.django_db
def test_get_product_orders_product_code_kosong():
    result = T.execute("get_product_orders", {"product_code": ""})
    assert result["ok"] is True and result.get("error") == "product_code_required"


@pytest.mark.django_db
def test_execute_masih_mendelegasikan_tool_v3():
    result = T.execute("count_records", {"entity": "order"})
    assert result["ok"] is True and isinstance(result["count"], int)
