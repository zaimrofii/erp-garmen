"""Cost tracker AI (F.4.1) — running total di cache + budget per user."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from ..config import AI_CONFIG

_MICRO = 1_000_000


def _day_of(timestamp) -> date:
    """Tanggal lokal (WIB) dari sebuah timestamp; fallback hari ini lokal."""
    if timestamp is None:
        return timezone.localdate()
    if timezone.is_aware(timestamp):
        return timezone.localtime(timestamp).date()
    return timestamp.date()


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _incr(key: str, amount: int) -> None:
    try:
        cache.incr(key, amount)
    except ValueError:
        current = int(cache.get(key, 0) or 0)
        cache.set(key, current + amount, timeout=None)


def _micro(value) -> int:
    return int(round(float(Decimal(str(value or 0))) * _MICRO))


def record_cost(decision_log) -> None:
    """Catat biaya 1 request (global hari, global bulan, per user bulan)."""
    timestamp = getattr(decision_log, "timestamp", None)
    day = _day_of(timestamp)
    micro = _micro(getattr(decision_log, "total_cost_usd", 0))
    if micro <= 0:
        return

    user_id = getattr(decision_log, "user_id", None)
    _incr(f"ai:cost:day:{day.isoformat()}", micro)
    _incr(f"ai:cost:month:{_month_key(day)}", micro)
    if user_id is not None:
        _incr(f"ai:cost:user:{user_id}:{_month_key(day)}", micro)


def get_daily_cost(day: date) -> Decimal:
    return Decimal(int(cache.get(f"ai:cost:day:{day.isoformat()}", 0) or 0)) / _MICRO


def get_monthly_cost(year: int, month: int) -> Decimal:
    key = f"ai:cost:month:{year:04d}-{month:02d}"
    return Decimal(int(cache.get(key, 0) or 0)) / _MICRO


def get_user_cost(user, month: int, year: int) -> Decimal:
    user_id = getattr(user, "pk", user)
    key = f"ai:cost:user:{user_id}:{year:04d}-{month:02d}"
    return Decimal(int(cache.get(key, 0) or 0)) / _MICRO


def check_budget(user) -> dict[str, Any]:
    """Bandingkan pemakaian bulan ini dengan budget user (default $5)."""
    today = timezone.localdate()
    used = get_user_cost(user, today.month, today.year)
    budget = Decimal(str(AI_CONFIG["observability"]["user_monthly_budget_usd"]))

    return {
        "exceeded": used > budget,
        "used_usd": used,
        "budget_usd": budget,
    }


def _reset_for_tests() -> None:
    for key in list(cache._cache.keys()) if hasattr(cache, "_cache") else []:
        if str(key).startswith("ai:cost:"):
            cache.delete(key)


__all__ = (
    "check_budget",
    "get_daily_cost",
    "get_monthly_cost",
    "get_user_cost",
    "record_cost",
)

