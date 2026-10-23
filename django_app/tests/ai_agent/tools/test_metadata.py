"""Test kontrak metadata di semua ToolResult (2+2+1)."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.validator import guard_answer
from integrations.ai_agent.tools import TOOLS, execute_tool

REQUIRED = ("metric", "dimension", "definition", "period", "source")
CALLS = {
    "list_records": {"entity": "order"},
    "count_records": {"entity": "order"},
    "get_record": {"entity": "order", "id_or_code": "TIDAK-ADA"},
    "aggregate": {"entity": "product", "field": "sale_price", "op": "max"},
    "get_metric": {"name": "garment.lead_time", "range": {"from": "2026-10-19", "to": "2026-10-23"}},
    "get_stock": {"product_code": "TIDAK-ADA"},
    "find_entity": {"entity": "work_center", "text": "SEWING"},
    "aggregate_operator": {"field": "event_count", "op": "count"},
    "get_product_orders": {"product_code": "TIDAK-ADA"},
    "propose_action": {"action_type": "audit", "entity_type": "order", "entity_id": "SO-1"},
}


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(TOOLS))
def test_setiap_tool_punya_metadata(name):
    result = execute_tool(name, CALLS[name], "SUPERVISOR")
    assert result.error is None or result.metadata, name
    for key in REQUIRED:
        assert result.metadata.get(key), f"{name} tanpa metadata.{key}"


def test_validator_menolak_trace_tanpa_metadata():
    trace = [{"tool": "count_records", "row_count": 1, "result": {"count": 12}, "metadata": {}}]
    verdict = guard_answer("12 order", trace, require_metadata=True)
    assert verdict[1]["ok"] is False
    assert verdict[1]["reason"] == "missing_metadata"


def test_validator_menerima_trace_dengan_metadata():
    trace = [
        {
            "tool": "count_records",
            "row_count": 1,
            "result": {"count": 12},
            "metadata": {
                "metric": "count",
                "dimension": "order",
                "definition": "jumlah baris",
                "period": "all-time",
                "source": "MES",
            },
        }
    ]
    verdict = guard_answer("12 order", trace, require_metadata=True)
    assert verdict[1]["ok"] is True
