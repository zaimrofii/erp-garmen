"""Definisi metrik (immutable) + kontrak compute/stream.

`MetricDefinition` sengaja **frozen** supaya plugin tidak bisa mengubah metrik
yang sudah terdaftar (registry menyimpan objek yang sama untuk semua pemanggil).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    """Satu metrik analytics.

    Aturan:
    - `metric_id` berformat ``<domain>.<name>`` (divalidasi di registry);
    - `compute` = fungsi **set-based** ``(filters) -> list[dict]`` (BUKAN loop
      per baris); aggregator yang memanggilnya;
    - `stream_check` opsional: ``None`` = metrik ini tidak punya alert stream;
    - `null_policy` default ``denominator_zero_returns_null`` (CONTRACT §8).
    """

    metric_id: str  # "garment.scrap_rate"
    domain: str  # "garment"
    label: str  # "Scrap Rate"
    unit: str  # "%", "pcs", "jam"
    granularities: list[str]  # ["hour", "day"]
    dimensions: list[str]  # ["period", "work_center", "line"]
    source_models: list[str]  # ["garment.ScrapAccumulator", ...]
    formula_version: str  # "1.0"
    compute: Callable[..., list[dict]]  # set-based aggregation
    null_policy: str = "denominator_zero_returns_null"
    thresholds: dict[str, Any] = field(default_factory=dict)
    stream_check: Callable[..., Any] | None = None


__all__ = ("MetricDefinition",)
