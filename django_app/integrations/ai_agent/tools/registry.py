"""Registri 9 tool produksi AI Agent (Fase 1).

Semua tool read-only. Akses dibatasi allowlist role per tool; eksekusi dicatat ke
`AIDecisionLog` (tool_name, args, row_count, duration_ms, executed).
"""

from __future__ import annotations

import json
import time

from . import (
    aggregate,
    aggregate_operator,
    count_records,
    find_entity,
    get_metric,
    get_product_orders,
    get_record,
    get_stock,
    list_records,
    propose_action,
)
from .base import (
    FORBIDDEN,
    INTERNAL_ERROR,
    INVALID_ARGUMENT,
    TOOL_NOT_FOUND,
    ToolResult,
    ToolSpec,
)

ALL_ROLES = frozenset(
    {"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"}
)

#: Metadata kontrak per tool: {metric, dimension, definition, source}.
TOOL_METADATA = {
    "list_records": {"metric": "rows", "dimension": "entity", "definition": "daftar baris entity", "source": "MES"},
    "count_records": {"metric": "count", "dimension": "entity", "definition": "jumlah baris entity", "source": "MES"},
    "get_record": {"metric": "record", "dimension": "entity", "definition": "detail satu baris entity", "source": "MES"},
    "aggregate": {"metric": "aggregate", "dimension": "entity", "definition": "agregasi field entity", "source": "MES"},
    "get_metric": {"metric": "garment_metric", "dimension": "work_center/period", "definition": "metrik analytics", "source": "MES"},
    "get_stock": {"metric": "stock_qty", "dimension": "product", "definition": "stok on-hand", "source": "Odoo"},
    "find_entity": {"metric": "matches", "dimension": "entity", "definition": "pencarian kode/nama", "source": "MES"},
    "aggregate_operator": {"metric": "operator_output", "dimension": "operator", "definition": "agregasi per operator (BUNDLE_FINISH)", "source": "MES"},
    "get_product_orders": {"metric": "orders", "dimension": "product", "definition": "order yang memuat produk", "source": "MES"},
    "propose_action": {"metric": "hitl_proposal", "dimension": "entity", "definition": "usulan tindakan ke HITL", "source": "MES"},
}


def _fill_metadata(name: str, result: ToolResult) -> ToolResult:
    """Pastikan setiap ToolResult punya metadata lengkap (kontrak 2+2+1)."""
    base = dict(TOOL_METADATA.get(name, {}))
    applied = result.filters_applied or {}
    period = applied.get("period")
    if not period and isinstance(applied.get("range"), dict):
        period = f"{applied['range'].get('from')}..{applied['range'].get('to')}"
    if not period:
        start = (applied.get("filters") or {}).get("created_at__date__gte")
        end = (applied.get("filters") or {}).get("created_at__date__lte")
        period = f"{start}..{end}" if start and end else "all-time"
    base.setdefault("period", str(period) if period else "all-time")
    merged = {**base, **(result.metadata or {})}
    for key in ("metric", "dimension", "definition", "period", "source"):
        merged.setdefault(key, "")
    result.metadata = merged
    return result



def _spec(module, roles, needs_user: bool = False) -> ToolSpec:
    schema = module.SCHEMA["function"]
    return ToolSpec(
        module.NAME,
        schema["description"],
        schema["parameters"],
        roles,
        module.run,
        needs_user=needs_user,
    )


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        _spec(list_records, list_records.ALL_ROLES),
        _spec(count_records, count_records.ALL_ROLES),
        _spec(get_record, get_record.ALL_ROLES),
        _spec(aggregate, aggregate.ALL_ROLES),
        _spec(get_metric, get_metric.SUPERVISOR_PLUS),
        _spec(get_stock, get_stock.STOCK_ROLES),
        _spec(find_entity, find_entity.ALL_ROLES),
        _spec(aggregate_operator, aggregate_operator.SUPERVISOR_PLUS),
        _spec(get_product_orders, get_product_orders.ALL_ROLES),
        _spec(propose_action, propose_action.SUPERVISOR_PLUS, needs_user=True),
    )
}


def get_tool(name: str) -> ToolSpec | None:
    return TOOLS.get(str(name or "").strip())


def get_tools_for_role(role: str) -> list[ToolSpec]:
    """Tool yang boleh dipakai role (allowlist). Role kosong -> tidak ada tool."""
    code = str(role or "").strip().upper()
    if not code:
        return []
    return [spec for spec in TOOLS.values() if spec.allows(code)]


def get_schemas_for_role(role: str) -> list[dict]:
    return [spec.schema() for spec in get_tools_for_role(role)]


def _known_arguments(spec: ToolSpec, args: dict) -> dict:
    properties = (spec.parameters or {}).get("properties") or {}
    return {key: value for key, value in args.items() if key in properties}


def _missing_required(spec: ToolSpec, args: dict) -> list[str]:
    required = list((spec.parameters or {}).get("required") or [])
    return [name for name in required if args.get(name) in (None, "")]


def _log_tool_call(
    user,
    name: str,
    args: dict,
    result: ToolResult,
    duration_ms: int,
    executed: bool,
) -> None:
    """Catat satu panggilan tool; kegagalan logging tidak boleh menggagalkan tool."""
    try:
        from ..observability.decision_logger import log_decision

        log_decision(
            user=user if getattr(user, "pk", None) else None,
            channel="AGENT",
            query_text=f"tool:{name}"[:500],
            decision_gate_result="TOOL",
            impact_score="LOW",
            tools_called=[
                {
                    "tool": name,
                    "args": {key: value for key, value in args.items() if key != "requested_by"},
                    "row_count": result.row_count,
                    "error": result.error,
                    "executed": executed,
                    "duration_ms": duration_ms,
                }
            ],
            response_text=json.dumps(
                {"warning": result.warnings, "error": result.error}, default=str
            )[:500],
            latency_ms=max(1, duration_ms),
        )
    except Exception:  # noqa: BLE001 - observability tidak boleh memblokir jawaban
        from logging import getLogger

        getLogger(__name__).warning("gagal mencatat tool call %s", name, exc_info=True)


def execute_tool(name: str, args: dict | None, role: str, user=None) -> ToolResult:
    """Validasi role + argumen, eksekusi tool, lalu catat trace."""
    started = time.monotonic()
    spec = get_tool(name)
    if spec is None:
        result = ToolResult.failure(TOOL_NOT_FOUND, f"tool {name!r} tidak dikenal")
        _log_tool_call(user, str(name), {}, result, 1, executed=False)
        return result

    code = str(role or "").strip().upper()
    if not spec.allows(code):
        result = ToolResult.failure(FORBIDDEN, f"role {code or 'kosong'} tidak boleh memakai {name}")
        _log_tool_call(user, name, {}, result, 1, executed=False)
        return result

    arguments = args if isinstance(args, dict) else {}
    arguments = _known_arguments(spec, arguments)
    if spec.needs_user:
        arguments["requested_by"] = user
    missing = _missing_required(spec, arguments)
    if missing:
        result = ToolResult.failure(INVALID_ARGUMENT, f"argumen wajib kosong: {', '.join(missing)}")
        _log_tool_call(user, name, arguments, result, 1, executed=False)
        return result

    executed = False
    try:
        result = spec.handler(**arguments)
        executed = True
    except ValueError as exc:
        result = ToolResult.failure(INVALID_ARGUMENT, str(exc))
    except TypeError as exc:
        result = ToolResult.failure(INVALID_ARGUMENT, f"argumen tidak sesuai: {exc}")
    except Exception as exc:  # noqa: BLE001 - agent butuh envelope, bukan 500
        result = ToolResult.failure(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

    duration_ms = max(1, int((time.monotonic() - started) * 1000))
    _fill_metadata(name, result)
    _log_tool_call(user, name, arguments, result, duration_ms, executed=executed)
    return result


__all__ = (
    "ALL_ROLES",
    "TOOLS",
    "execute_tool",
    "get_schemas_for_role",
    "get_tool",
    "get_tools_for_role",
)

