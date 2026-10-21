"""MCP `forecaster` (H T3.2) — prediksi metrik & completion READ-ONLY."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps_industry.garment.models import Bundle, Order

from . import mcp_time_series

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
VALID_METRICS = {"garment.scrap_rate", "garment.rework_rate", "garment.lead_time"}
VALID_METHODS = {"ma", "linear"}
MIN_POINTS = 7
MAX_HORIZON = 30
SCHEMA = {
    "forecast_metric": {
        "metric_id": "str",
        "horizon_days": "int",
        "method": "str?",
    },
    "predict_completion": {"order_id": "int|str", "method": "str?"},
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _as_date(value: Any, fallback: date | None = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_datetime(str(value or ""))
    return parsed.date() if parsed else (fallback or timezone.localdate())


def _series(metric_id: str, user) -> list[dict]:
    now = timezone.now()
    result = mcp_time_series.handle(
        "get_metric_series",
        {
            "metric_id": metric_id,
            "granularity": "day",
            "period_from": (now - timedelta(days=30)).isoformat(),
            "period_to": now.isoformat(),
        },
        user=user,
    )
    if not result.get("ok"):
        return []
    return [
        row
        for row in result.get("series") or []
        if row.get("value") is not None
    ]


def _linear(values: list[float], x: int) -> tuple[float, float]:
    """OLS sederhana (tanpa numpy; dependency tidak terpasang)."""
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denominator = sum((i - mean_x) ** 2 for i in xs)
    slope = (
        sum((i - mean_x) * (value - mean_y) for i, value in zip(xs, values))
        / denominator
        if denominator
        else 0.0
    )
    intercept = mean_y - slope * mean_x
    return intercept + slope * x, slope


def _forecast(metric_id: str, horizon_days: int, method: str, user) -> dict:
    rows = _series(metric_id, user)
    if len(rows) < MIN_POINTS:
        return _error(
            "insufficient_data",
            f"Data historis < {MIN_POINTS} hari ({len(rows)}).",
        )

    values = [float(row["value"]) for row in rows]
    dates = [_as_date(row.get("period")) for row in rows]
    last_date = dates[-1]
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0

    forecast = []
    for step in range(1, horizon_days + 1):
        if method == "ma":
            window = values[-7:]
            mid = sum(window) / len(window)
        else:
            mid, _ = _linear(values, len(values) + step - 1)
        margin = 1.96 * stdev
        forecast.append(
            {
                "date": (last_date + timedelta(days=step)).isoformat(),
                "value_low": round(max(0.0, mid - margin), 6),
                "value_mid": round(max(0.0, mid), 6),
                "value_high": round(max(0.0, mid + margin), 6),
            }
        )

    return {
        "ok": True,
        "method": method,
        "metric_id": metric_id,
        "horizon_days": horizon_days,
        "forecast": forecast,
        "confidence": 0.95,
    }


def _order(order_id: Any) -> Order | None:
    raw = str(order_id or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return Order.objects.filter(pk=int(raw)).first()
    return Order.objects.filter(code=raw).first()


def _predict_completion(order_id: Any) -> dict:
    order = _order(order_id)
    if order is None:
        return _error("not_found", "Order tidak ditemukan.")

    bundles = list(
        Bundle.objects.filter(work_order__order_line__order=order).select_related(
            "work_order"
        )
    )
    planned = sum(float(bundle.work_order.qty_planned or 0) for bundle in bundles)
    done = sum(float(bundle.qty_done or 0) for bundle in bundles)
    if not bundles or planned <= 0:
        return _error("no_data", "Order belum memiliki bundle/qty rencana.")

    today = timezone.localdate()
    if str(order.state).upper() == "DONE" or done >= planned:
        return {
            "ok": True,
            "order_code": order.code,
            "estimated_completion_date": today.isoformat(),
            "confidence": 0.99,
            "days_remaining": 0,
            "progress_pct": round(min(100.0, done / planned * 100), 2),
        }

    elapsed_days = max(1.0, (timezone.now() - order.created_at).total_seconds() / 86400)
    rate = done / elapsed_days
    if rate <= 0:
        return _error("insufficient_data", "Belum ada progres produksi.")

    remaining = max(0.0, planned - done)
    days_remaining = max(1, math.ceil(remaining / rate))
    return {
        "ok": True,
        "order_code": order.code,
        "estimated_completion_date": (today + timedelta(days=days_remaining)).isoformat(),
        "confidence": 0.8,
        "days_remaining": days_remaining,
        "progress_pct": round(done / planned * 100, 2),
        "production_rate_per_day": round(rate, 4),
    }


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Prediksi read-only; fail-safe bila data tidak cukup."""
    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses forecaster.")
    if method not in SCHEMA:
        return _error("method_tidak_dikenal", str(method))

    data = params or {}
    method_name = str(data.get("method") or "ma").strip().lower()
    if method_name not in VALID_METHODS:
        return _error("method_invalid", method_name)

    try:
        if method == "predict_completion":
            return _predict_completion(data.get("order_id"))

        metric_id = str(data.get("metric_id") or "").strip()
        if metric_id not in VALID_METRICS:
            return _error("metric_id_tidak_dikenal", metric_id)
        try:
            horizon = int(data.get("horizon_days") or 1)
        except (TypeError, ValueError):
            return _error("horizon_invalid", str(data.get("horizon_days")))
        if horizon < 1 or horizon > MAX_HORIZON:
            return _error("horizon_invalid", str(horizon))
        return _forecast(metric_id, horizon, method_name, user)
    except Exception as exc:  # noqa: BLE001 - fail-safe ke AI
        return _error("forecast_error", type(exc).__name__)


def register(registry) -> None:
    registry.register("mcp-forecaster", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")

