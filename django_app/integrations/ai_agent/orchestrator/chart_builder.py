"""Chart data dari konteks metrik (Fix #18C) — PURE, tanpa I/O."""

from __future__ import annotations

from typing import Any

MONTHS_ID = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)

CHART_INTENTS = {"ANALYTICS_QUERY", "DIAGNOSTIC"}
METRIC_TITLES = {
    "garment.scrap_rate": "Scrap",
    "garment.rework_rate": "Rework",
    "garment.lead_time": "Lead Time",
    "garment.line_balance": "Line Balance",
    "garment.bottleneck": "Bottleneck",
    "garment.oee": "OEE",
    "garment.wip_flow": "WIP Flow",
}
MAX_POINTS = 14

_METRIC_KEYWORDS = (
    ("lead time", "garment.lead_time"),
    ("lead_time", "garment.lead_time"),
    ("rework", "garment.rework_rate"),
    ("scrap", "garment.scrap_rate"),
    ("oee", "garment.oee"),
    ("wip", "garment.wip_flow"),
    ("wip_flow", "garment.wip_flow"),
)
_NO_CHART_WORDS = ("bottleneck", "line balance", "line_balance")


def _requested_metric(message: str) -> str | None:
    """Metrik yang disebut user; None bila tidak ada metrik yang jelas."""
    text = str(message or "").lower()
    if any(word in text for word in _NO_CHART_WORDS):
        return None
    for keyword, metric_id in _METRIC_KEYWORDS:
        if keyword in text:
            return metric_id
    return None


def _label(raw: Any) -> str:
    text = str(raw or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            day = int(text[8:10])
            month = int(text[5:7])
        except ValueError:
            return text
        if 1 <= month <= 12:
            return f"{day} {MONTHS_ID[month - 1]}"
    return text


def _points(rows: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_label = row.get("label") or row.get("date") or row.get("key")
        value = row.get("value")
        if raw_label is None or isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        points.append({"label": _label(raw_label), "value": round(float(value), 2)})
    return points


def build_chart_data(
    context_data: dict, intent: str, message: str = ""
) -> dict[str, Any] | None:
    """Pilih series metrik yang diminta user → kontrak chart frontend.

    Chart hanya dibuat bila pesan menyebut metrik yang jelas (scrap/rework/
    lead time/oee/wip) atau kata tren/grafik. Tidak ada fallback ke metrik
    pertama. ``bottleneck`` bukan tren sehingga tidak memicu chart.
    """
    if not isinstance(context_data, dict):
        return None
    if str(intent or "").strip().upper() not in CHART_INTENTS:
        return None

    text = str(message or "").lower()
    metric_id = _requested_metric(text)
    if metric_id is None:
        return None

    existing = context_data.get("chart_data")
    if isinstance(existing, dict) and isinstance(existing.get("data"), list):
        return existing

    metrics = context_data.get("metrics")
    if not isinstance(metrics, list):
        return None

    for entry in metrics:
        if not isinstance(entry, dict):
            continue
        if entry.get("dimension") not in (None, "period"):
            continue
        if str(entry.get("metric_id") or "") != metric_id:
            continue
        points = _points(entry.get("rows"))
        if len(points) < 2:
            return None
        name = METRIC_TITLES.get(metric_id, metric_id)
        return {
            "type": "line",
            "title": f"Tren {name}",
            "data": points[-MAX_POINTS:],
            "unit": str(entry.get("unit") or ""),
            "metric_id": metric_id,
        }

    return None


__all__ = ("CHART_INTENTS", "METRIC_TITLES", "build_chart_data")
