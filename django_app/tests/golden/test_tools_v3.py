"""Unit test 7 tool generik (desain validasi). Tanpa LLM."""

from __future__ import annotations

import pytest

from apps_industry.garment.models import Order
from master.models import Partner
from tests.golden import spike_tools_v3 as T
from tests.golden.spike_tools_v3 import TOOLS_SCHEMA


def _tool(name: str) -> dict:
    return next(t for t in TOOLS_SCHEMA if t["function"]["name"] == name)


def test_schema_menyediakan_date_from_date_to():
    for name in ("list_records", "count_records", "aggregate"):
        props = _tool(name)["function"]["parameters"]["properties"]
        assert "date_from" in props and "date_to" in props


def test_schema_get_metric_menyebut_stats():
    assert "stats" in _tool("get_metric")["function"]["description"]


@pytest.mark.django_db
def test_get_metric_envelope_stats_lengkap():
    result = T.execute(
        "get_metric",
        {"name": "garment.lead_time", "range": {"from": "2026-10-19", "to": "2026-10-22"}},
    )
    assert result["ok"] is True, result
    assert set(result["stats"]) == {"avg", "latest", "min", "max", "count", "sum"}
    assert isinstance(result["series"], list)
    assert "warnings" in result


@pytest.mark.django_db
def test_get_metric_periode_kosong_stats_null():
    result = T.execute(
        "get_metric",
        {"name": "garment.lead_time", "range": {"from": "2020-01-01", "to": "2020-01-02"}},
    )
    assert result["stats"]["count"] == 0
    assert result["stats"]["avg"] is None
    assert result["stats"]["sum"] == 0
    assert "no_data_in_period" in result["warnings"]


@pytest.mark.django_db
def test_list_records_order_punya_field_turunan():
    partner = Partner.objects.create(code="T-CUST-1", name="Test Customer", is_customer=True)
    Order.objects.create(code="T-ORD-1", customer=partner, state="DONE")
    result = T.execute("list_records", {"entity": "order", "filters": {"code": "T-ORD-1"}})
    assert result["ok"] is True and result["rows"]
    row = result["rows"][0]
    assert {"is_late", "days_late", "days_remaining"} <= set(row)


@pytest.mark.django_db
def test_get_record_order_punya_field_turunan():
    partner = Partner.objects.create(code="T-CUST-2", name="Test Customer 2", is_customer=True)
    Order.objects.create(code="T-ORD-2", customer=partner, state="DRAFT")
    result = T.execute("get_record", {"entity": "order", "id_or_code": "T-ORD-2"})
    assert result["ok"] is True
    assert "days_remaining" in result["record"]


@pytest.mark.django_db
def test_count_records_mengembalikan_count():
    result = T.execute("count_records", {"entity": "product"})
    assert result["ok"] is True and isinstance(result["count"], int)


@pytest.mark.django_db
def test_aggregate_mengembalikan_rows():
    result = T.execute(
        "aggregate", {"entity": "product", "field": "sale_price", "op": "max"}
    )
    assert result["ok"] is True and result["rows"]
    assert "max_sale_price" in result["rows"][0]


@pytest.mark.django_db
def test_find_entity_envelope_matches():
    result = T.execute("find_entity", {"entity": "work_center", "text": "SEWING"})
    assert result["ok"] is True
    assert {"matches", "ambiguous", "count"} <= set(result)


@pytest.mark.django_db
def test_find_entity_tidak_ditemukan():
    result = T.execute("find_entity", {"entity": "product", "text": "TIDAK-ADA-XYZ"})
    assert result["matches"] == [] and result["count"] == 0


@pytest.mark.django_db
def test_get_stock_envelope():
    result = T.execute("get_stock", {"product_code": "ODOO-65"})
    assert result["ok"] is True
    assert {"product_code", "quantity", "reserved", "available", "uom"} <= set(result)
