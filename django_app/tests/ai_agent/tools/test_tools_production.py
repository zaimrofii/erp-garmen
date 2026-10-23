"""Test 9 tool produksi (Fase 1) — tanpa LLM."""

from __future__ import annotations

import pytest

from apps_industry.garment.models import Order
from integrations.ai_agent.tools import (
    FORBIDDEN,
    INVALID_ARGUMENT,
    NO_DATA,
    TOOL_NOT_FOUND,
    TOOLS,
    ToolResult,
    aggregate,
    aggregate_operator,
    count_records,
    execute_tool,
    find_entity,
    get_metric,
    get_product_orders,
    get_record,
    get_schemas_for_role,
    get_stock,
    get_tools_for_role,
    list_records,
)
from master.models import Partner

ENVELOPE_KEYS = {"ok", "error", "data", "row_count", "truncated", "as_of", "filters_applied", "warnings"}


def test_registry_berisi_sepuluh_tool():
    assert len(TOOLS) == 10
    assert set(TOOLS) == {
        "list_records",
        "count_records",
        "get_record",
        "aggregate",
        "get_metric",
        "get_stock",
        "find_entity",
        "aggregate_operator",
        "get_product_orders",
        "propose_action",
    }


def test_allowlist_role():
    operator_tools = {spec.name for spec in get_tools_for_role("OPERATOR")}
    assert "get_metric" not in operator_tools
    assert "aggregate_operator" not in operator_tools
    assert "get_stock" not in operator_tools
    assert "propose_action" not in operator_tools
    supervisor_tools = {spec.name for spec in get_tools_for_role("SUPERVISOR")}
    assert len(supervisor_tools) == 10
    assert get_tools_for_role("") == []


def test_schema_tools_sesuai_role():
    schemas = get_schemas_for_role("QC")
    names = {item["function"]["name"] for item in schemas}
    assert "get_metric" not in names and "find_entity" in names
    assert all(item["type"] == "function" for item in schemas)


@pytest.mark.django_db
def test_list_records_envelope():
    partner = Partner.objects.create(code="F1-CUST", name="Fase 1 Customer", is_customer=True)
    Order.objects.create(code="F1-ORD", customer=partner, state="DRAFT")
    result = list_records.run("order", filters={"code": "F1-ORD"})
    assert isinstance(result, ToolResult)
    payload = result.to_dict()
    assert ENVELOPE_KEYS <= set(payload)
    assert payload["ok"] is True
    assert result.row_count == 1
    assert result.data["rows"][0]["is_late"] is False


@pytest.mark.django_db
def test_count_records_envelope():
    result = count_records.run("order")
    assert result.ok and isinstance(result.data["count"], int)


@pytest.mark.django_db
def test_get_record_envelope():
    partner = Partner.objects.create(code="F1-CUST-2", name="Customer 2", is_customer=True)
    Order.objects.create(code="F1-ORD-2", customer=partner, state="DRAFT")
    result = get_record.run("order", "F1-ORD-2", include=["customer"])
    assert result.ok and result.data["record"]["code"] == "F1-ORD-2"
    assert "days_remaining" in result.data["record"]


@pytest.mark.django_db
def test_get_record_tidak_ditemukan_no_data():
    result = get_record.run("order", "TIDAK-ADA")
    assert result.error == NO_DATA


@pytest.mark.django_db
def test_aggregate_envelope():
    result = aggregate.run("product", "sale_price", "max")
    assert result.ok and result.row_count == 1


@pytest.mark.django_db
def test_aggregate_scrap_menerapkan_filter_tanggal():
    """Regresi G028: periode harus benar-benar memfilter entity scrap."""
    result = aggregate.run(
        "scrap", "qty", "sum", date_from="2020-01-01", date_to="2020-01-02"
    )
    assert result.ok
    applied = result.filters_applied["filters"]
    assert str(applied["created_at__date__gte"]) == "2020-01-01"
    assert str(applied["created_at__date__lte"]) == "2020-01-02"


@pytest.mark.django_db
def test_list_records_filter_is_active():
    from master.models import Product

    Product.objects.create(code="F2-AKTIF", name="Produk Aktif", sale_price=1000, is_active=True)
    Product.objects.create(code="F2-NONAKTIF", name="Produk Nonaktif", sale_price=1000, is_active=False)
    result = list_records.run("product", filters={"is_active": True, "code__startswith": "F2-"})
    codes = {row["code"] for row in result.data["rows"]}
    assert codes == {"F2-AKTIF"}


@pytest.mark.django_db
def test_get_metric_envelope_stats():
    result = get_metric.run(
        "garment.lead_time", {"from": "2026-10-19", "to": "2026-10-23"}
    )
    assert result.ok
    assert set(result.data["stats"]) == {"avg", "latest", "min", "max", "count", "sum"}


@pytest.mark.django_db
def test_find_entity_envelope():
    result = find_entity.run("work_center", "SEWING")
    assert result.ok and {"matches", "ambiguous", "count"} <= set(result.data)


@pytest.mark.django_db
def test_aggregate_operator_event_count_hanya_finish():
    """G024: event_count = jumlah event BUNDLE_FINISH, bukan semua tipe event."""
    from django.db.models import Count

    from apps_industry.garment.models import BundleEvent

    expected = {
        row["actor__username"]: row["value"]
        for row in BundleEvent.objects.filter(
            event_type="BUNDLE_FINISH", actor__isnull=False
        )
        .values("actor__username")
        .annotate(value=Count("id"))
    }
    result = aggregate_operator.run("event_count", "count", limit=100)
    got = {row["operator"]: int(row["value"]) for row in result.data["rows"]}
    assert got == expected


@pytest.mark.django_db
def test_aggregate_operator_envelope():
    result = aggregate_operator.run("event_count", "count")
    assert result.ok
    assert {"rows", "period"} <= set(result.data)
    assert isinstance(result.row_count, int)
    assert result.filters_applied["field"] == "event_count"


@pytest.mark.django_db
def test_get_product_orders_produk_tidak_ada():
    result = get_product_orders.run("TIDAK-ADA-XYZ")
    assert result.error == NO_DATA


@pytest.mark.django_db
def test_get_stock_tanpa_erp_atau_envelope():
    result = get_stock.run("TIDAK-ADA-XYZ")
    assert result.ok or result.error in {"erp_not_configured", "internal_error"}


@pytest.mark.django_db
def test_execute_tool_operator_forbidden():
    result = execute_tool("get_metric", {"name": "garment.lead_time"}, "OPERATOR")
    assert result.error == FORBIDDEN


@pytest.mark.django_db
def test_execute_tool_argumen_kurang_invalid():
    result = execute_tool("aggregate", {"entity": "product", "field": "sale_price"}, "SUPERVISOR")
    assert result.error == INVALID_ARGUMENT


@pytest.mark.django_db
def test_execute_tool_argumen_salah_invalid():
    result = execute_tool(
        "get_metric",
        {"name": "garment.lead_time", "range": {"from": "2020-01-02", "to": "2020-01-01"}},
        "SUPERVISOR",
    )
    assert result.error == INVALID_ARGUMENT


@pytest.mark.django_db
def test_execute_tool_tidak_dikenal():
    result = execute_tool("hapus_order", {}, "ADMIN")
    assert result.error == TOOL_NOT_FOUND


@pytest.mark.django_db
def test_execute_tool_tercatat_di_decision_log():
    from integrations.ai_agent.models import AIDecisionLog

    execute_tool("count_records", {"entity": "order"}, "SUPERVISOR")
    log = AIDecisionLog.objects.filter(decision_gate_result="TOOL").latest("timestamp")
    assert log.tools_called[0]["tool"] == "count_records"
    assert log.tools_called[0]["executed"] is True
