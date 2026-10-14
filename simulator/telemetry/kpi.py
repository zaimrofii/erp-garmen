"""KPI aggregator dari file JSONL telemetry — fase M4.

Menghitung ringkasan operasional dari jejak ``Recorder`` (satu JSON per aksi):
success/error, latency persentil (p50/p95/p99), rasio keputusan LLM vs scripted,
serta breakdown per agent & per endpoint.

Sengaja **stdlib saja** (``json`` + ``statistics``) — tanpa numpy/pandas, tanpa
state: fungsi murni, file masuk → dict keluar. File tidak ada → semua nilai 0.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ("compute_kpi",)


def _empty() -> dict:
    """KPI kosong (dipakai saat file tidak ada / tanpa baris valid)."""

    return {
        "total_actions": 0,
        "success_count": 0,
        "error_count": 0,
        "error_rate": 0.0,
        "latency_p50": 0.0,
        "latency_p95": 0.0,
        "latency_p99": 0.0,
        "llm_decision_rate": 0.0,
        "scripted_decision_rate": 0.0,
        "by_agent": {},
        "by_endpoint": {},
    }


def _is_success(rec: dict) -> bool:
    """Aksi sukses = punya ``status_code`` 2xx."""

    sc = rec.get("status_code")
    return isinstance(sc, int) and 200 <= sc < 300


def _is_error(rec: dict) -> bool:
    """Error = baris ``record_error`` (punya ``error``) ATAU ``status_code`` >= 400."""

    if rec.get("error") is not None:
        return True
    sc = rec.get("status_code")
    return isinstance(sc, int) and sc >= 400


def _percentile(values: list[float], p: int) -> float:
    """Persentil ke-``p`` via ``statistics.quantiles``; < 2 sampel → 0.0."""

    if len(values) < 2:
        return 0.0
    cuts = statistics.quantiles(values, n=100, method="inclusive")  # 99 titik (p1..p99)
    return float(cuts[p - 1])


def compute_kpi(jsonl_path: str) -> dict:
    """Baca JSONL dan kembalikan dict KPI (lihat :func:`_empty` untuk bentuk)."""

    path = Path(jsonl_path)
    if not path.is_file():
        return _empty()

    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("baris JSONL tidak valid dilewati: %.80s", line)
                continue

    total = len(records)
    if total == 0:
        return _empty()

    success = sum(1 for r in records if _is_success(r))
    error = sum(1 for r in records if _is_error(r))
    latencies = [float(r["latency_ms"]) for r in records
                 if isinstance(r.get("latency_ms"), (int, float))]
    llm = sum(1 for r in records if r.get("decision_source") == "llm")
    scripted = sum(1 for r in records if r.get("decision_source") == "scripted")

    by_agent: dict = {}
    by_endpoint: dict = {}
    agent_lat: dict = {}
    for r in records:
        aid = r.get("agent_id", "?")
        ep = r.get("endpoint", "?")
        a = by_agent.setdefault(
            aid, {"total": 0, "success": 0, "error": 0, "avg_latency_ms": 0.0}
        )
        a["total"] += 1
        a["success"] += 1 if _is_success(r) else 0
        a["error"] += 1 if _is_error(r) else 0
        if isinstance(r.get("latency_ms"), (int, float)):
            agent_lat.setdefault(aid, []).append(float(r["latency_ms"]))

        e = by_endpoint.setdefault(ep, {"total": 0, "success": 0, "error": 0})
        e["total"] += 1
        e["success"] += 1 if _is_success(r) else 0
        e["error"] += 1 if _is_error(r) else 0

    for aid, vals in agent_lat.items():
        by_agent[aid]["avg_latency_ms"] = sum(vals) / len(vals)

    return {
        "total_actions": total,
        "success_count": success,
        "error_count": error,
        "error_rate": error / total,
        "latency_p50": _percentile(latencies, 50),
        "latency_p95": _percentile(latencies, 95),
        "latency_p99": _percentile(latencies, 99),
        "llm_decision_rate": llm / total,
        "scripted_decision_rate": scripted / total,
        "by_agent": by_agent,
        "by_endpoint": by_endpoint,
    }
