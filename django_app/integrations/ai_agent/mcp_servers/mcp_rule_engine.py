"""MCP `rule-engine` (H T2.1) — evaluasi aturan bisnis READ-ONLY."""

from __future__ import annotations

import time
from typing import Any

from apps_industry.garment.models import Bundle, BundleEvent, MaterialReadiness, Order
from core.rule_engine.services import RuleEngine
from integrations.ai_agent.config import AI_CONFIG

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
SCHEMA = {
    "can_start_production": {"bundle_id": "int"},
    "check_rework_needed": {"bundle_id": "int"},
    "check_stock_sufficient": {"order_id": "int"},
    "check_order_can_confirm": {"order_id": "int"},
    "evaluate_rule": {"rule_code": "str", "facts": "dict"},
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _result(method: str, result: bool, reason: str, details: dict | None = None) -> dict:
    return {
        "ok": bool(result),
        "method": method,
        "result": bool(result),
        "reason": reason,
        "details": details or {},
    }


def _timed_out(started: float) -> bool:
    timeout = float(AI_CONFIG.get("mcp", {}).get("timeout_seconds", 5))
    return (time.monotonic() - started) > timeout


def _bundle(bundle_id: Any) -> Bundle | None:
    try:
        return (
            Bundle.objects.select_related(
                "work_order__order_line__readiness", "current_work_center"
            )
            .filter(pk=int(bundle_id))
            .first()
        )
    except (TypeError, ValueError):
        return None


def _readiness(bundle: Bundle):
    return getattr(bundle.work_order.order_line, "readiness", None)


def _can_start_production(params: dict) -> dict:
    bundle = _bundle(params.get("bundle_id"))
    if bundle is None:
        return _error("not_found", "Bundle tidak ditemukan.")

    readiness = _readiness(bundle)
    material_ok = bool(
        readiness
        and (
            readiness.status == MaterialReadiness.Status.READY
            or readiness.received_qty >= readiness.required_qty
        )
    )
    wc = bundle.current_work_center
    wc_ok = wc is None or bool(wc.is_active)
    result = material_ok and wc_ok
    if not readiness:
        reason = "Material readiness belum dihitung."
    elif not material_ok:
        reason = "Material belum siap (READY belum terpenuhi)."
    elif not wc_ok:
        reason = "Work center tidak aktif."
    else:
        reason = "Material siap dan work center tersedia."
    return _result(
        "can_start_production",
        result,
        reason,
        {
            "bundle": bundle.code,
            "material_status": getattr(readiness, "status", None),
            "required_qty": getattr(readiness, "required_qty", None),
            "received_qty": getattr(readiness, "received_qty", None),
            "work_center": getattr(wc, "code", None),
            "work_center_active": getattr(wc, "is_active", None),
        },
    )


def _check_rework_needed(params: dict) -> dict:
    bundle = _bundle(params.get("bundle_id"))
    if bundle is None:
        return _error("not_found", "Bundle tidak ditemukan.")

    events = BundleEvent.objects.filter(
        bundle=bundle, event_type__in=["QC_FAIL", "REWORK"]
    )
    result = events.exists()
    reason = "Ada event QC_FAIL/REWORK." if result else "Tidak ada event QC_FAIL/REWORK."
    return _result(
        "check_rework_needed",
        result,
        reason,
        {"bundle": bundle.code, "event_count": events.count()},
    )


def _order(order_id: Any) -> Order | None:
    try:
        return Order.objects.filter(pk=int(order_id)).first()
    except (TypeError, ValueError):
        return None


def _check_stock_sufficient(params: dict) -> dict:
    order = _order(params.get("order_id"))
    if order is None:
        return _error("not_found", "Order tidak ditemukan.")

    lines = list(order.lines.all())
    readiness = [getattr(line, "readiness", None) for line in lines]
    if not lines or any(row is None for row in readiness):
        return _result(
            "check_stock_sufficient",
            False,
            "Material readiness belum lengkap.",
            {"order": order.code, "line_count": len(lines)},
        )

    sufficient = all(
        row.status == MaterialReadiness.Status.READY and row.shortage_qty <= 0
        for row in readiness
    )
    return _result(
        "check_stock_sufficient",
        sufficient,
        "Semua material siap." if sufficient else "Masih ada kekurangan material.",
        {
            "order": order.code,
            "line_count": len(lines),
            "shortage_total": sum(float(row.shortage_qty or 0) for row in readiness),
        },
    )


def _check_order_can_confirm(params: dict) -> dict:
    order = _order(params.get("order_id"))
    if order is None:
        return _error("not_found", "Order tidak ditemukan.")

    lines = list(order.lines.all())
    readiness = [getattr(line, "readiness", None) for line in lines]
    prices_ok = bool(lines) and all(float(line.price_unit or 0) > 0 for line in lines)
    material_ok = bool(readiness) and all(
        row is not None
        and row.status == MaterialReadiness.Status.READY
        and row.shortage_qty <= 0
        for row in readiness
    )
    state_ok = str(order.state).upper() == "DRAFT"
    result = state_ok and prices_ok and material_ok

    if not state_ok:
        reason = f"State order {order.state} bukan DRAFT."
    elif not prices_ok:
        reason = "Harga baris order belum lengkap/positif."
    elif not material_ok:
        reason = "Material belum siap."
    else:
        reason = "Order siap dikonfirmasi."
    return _result(
        "check_order_can_confirm",
        result,
        reason,
        {
            "order": order.code,
            "state": order.state,
            "line_count": len(lines),
            "state_ok": state_ok,
            "prices_ok": prices_ok,
            "material_ok": material_ok,
        },
    )


def _evaluate_rule(params: dict) -> dict:
    rule_code = str(params.get("rule_code") or "").strip()
    if not rule_code:
        return _error("bad_request", "rule_code wajib diisi.")
    outcome = RuleEngine().evaluate(rule_code, params.get("facts") or {})
    return _result(
        "evaluate_rule",
        outcome.matched,
        outcome.reason,
        {
            "rule_code": rule_code,
            "actions": outcome.actions,
            "matched": outcome.matched,
        },
    )


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Evaluasi rule bisnis — read-only, fail-safe."""
    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses rule engine.")
    if method not in SCHEMA:
        return _error("method_tidak_dikenal", str(method))

    started = time.monotonic()
    if _timed_out(started):
        return _error("rule_error", "Timeout evaluasi rule.")

    data = params or {}
    try:
        if method == "can_start_production":
            return _can_start_production(data)
        if method == "check_rework_needed":
            return _check_rework_needed(data)
        if method == "check_stock_sufficient":
            return _check_stock_sufficient(data)
        if method == "check_order_can_confirm":
            return _check_order_can_confirm(data)
        return _evaluate_rule(data)
    except Exception as exc:  # noqa: BLE001 - fail-safe ke AI
        return _error("rule_error", type(exc).__name__)


def register(registry) -> None:
    registry.register("mcp-rule-engine", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")


