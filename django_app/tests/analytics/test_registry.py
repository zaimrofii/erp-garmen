"""Test registry metrik analytics (B.1).

Enam skenario fondasi:
1. register sukses;
2. duplikat → ValueError (+ validasi format metric_id);
3. get tidak ada → KeyError;
4. discover idempoten;
5. filter domain;
6. MetricDefinition frozen (immutable).
"""

from __future__ import annotations

import dataclasses

import pytest

from integrations.analytics.core import registry
from integrations.analytics.core.metric import MetricDefinition


@pytest.fixture(autouse=True)
def reset_registry():
    """Registry bersih per test + baseline plugin garment (3 metrik sejak B.6)."""
    registry._reset_for_tests()
    registry.discover_metrics()
    yield
    registry._reset_for_tests()


def _make_metric(
    metric_id: str = "garment.test_metric", domain: str = "garment"
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        domain=domain,
        label="Test",
        unit="%",
        granularities=["day"],
        dimensions=["period"],
        source_models=["garment.BundleEvent"],
        formula_version="1.0",
        compute=lambda filters: [],
    )


def test_register_metric_success():
    baseline = len(registry.list_metrics())
    registry.register_metric(_make_metric())

    assert len(registry.list_metrics()) == baseline + 1
    assert registry.get_metric("garment.test_metric").label == "Test"


def test_register_metric_duplicate_raises():
    registry.register_metric(_make_metric())

    with pytest.raises(ValueError, match="duplikat"):
        registry.register_metric(_make_metric())

    # Validasi format: tanpa titik / domain tidak cocok → ValueError.
    with pytest.raises(ValueError, match="format"):
        registry.register_metric(_make_metric(metric_id="tanpa_titik"))
    with pytest.raises(ValueError, match="domain"):
        registry.register_metric(_make_metric(metric_id="rmu.lain"))


def test_get_metric_not_found():
    with pytest.raises(KeyError):
        registry.get_metric("garment.nonexistent")


def test_discover_metrics_idempotent():
    # Plugin garment berisi 3 metrik (B.6) — discover harus idempoten.
    n1 = registry.discover_metrics()
    n2 = registry.discover_metrics()

    assert n1 == n2 == 3


def test_list_metrics_filter_domain():
    garment_baseline = len(registry.list_metrics("garment"))
    registry.register_metric(_make_metric("garment.a", "garment"))
    registry.register_metric(_make_metric("rmu.b", "rmu"))

    assert len(registry.list_metrics("garment")) == garment_baseline + 1
    assert len(registry.list_metrics("rmu")) == 1
    assert len(registry.list_metrics()) == garment_baseline + 1 + 1


def test_metric_definition_immutable():
    metric = _make_metric()

    with pytest.raises(dataclasses.FrozenInstanceError):
        metric.metric_id = "garment.changed"  # type: ignore[misc]
