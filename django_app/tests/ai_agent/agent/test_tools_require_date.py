"""Test date range wajib di get_metric (demo-ready)."""

from __future__ import annotations

import pytest

from integrations.ai_agent.tools import get_metric


@pytest.mark.django_db
def test_get_metric_tanpa_range_ditolak():
    result = get_metric.run("garment.lead_time")
    assert result.error == "missing_date_range"
    assert result.data == {}


@pytest.mark.django_db
def test_get_metric_dengan_range_konsisten():
    first = get_metric.run("garment.lead_time", {"from": "2026-10-19", "to": "2026-10-23"})
    second = get_metric.run("garment.lead_time", {"from": "2026-10-19", "to": "2026-10-23"})
    assert first.ok and second.ok
    assert first.data["stats"] == second.data["stats"]
    assert first.data["period"] == {"from": "2026-10-19", "to": "2026-10-23"}
