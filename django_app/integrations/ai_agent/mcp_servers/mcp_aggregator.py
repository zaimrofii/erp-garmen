"""MCP `aggregator` (H T2.2) — SUM/AVG/COUNT/MIN/MAX/P50/P90 READ-ONLY."""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps
from django.db import connection
from django.db.models import Avg, Count, Max, Min, Sum

from .mcp_postgres_query import ALLOWLIST

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
VALID_AGGS = {"sum", "avg", "count", "min", "max", "p50", "p90"}
MAX_PERCENTILE_ROWS = 100_000
SCHEMA = {
    "aggregate": {
        "table": "str",
        "column": "str",
        "agg": "str",
        "filters": "dict?",
        "group_by": "str?",
    }
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _validate(params: dict):
    table = params.get("table")
    if not isinstance(table, str) or table not in ALLOWLIST:
        return None, _error("table_not_allowed")

    app_label, model_name, columns = ALLOWLIST[table]
    column = params.get("column")
    if not isinstance(column, str) or column not in columns:
        return None, _error("column_not_allowed")

    agg = str(params.get("agg") or "").strip().lower()
    if agg not in VALID_AGGS:
        return None, _error("agg_not_allowed", str(agg))

    filters = params.get("filters") or {}
    if not isinstance(filters, dict):
        return None, _error("filters_invalid")
    for key, value in filters.items():
        base = str(key).split("__", 1)[0]
        if base not in columns:
            return None, _error("filters_not_allowed", str(key))
        if not isinstance(value, (str, int, float, bool, type(None))):
            return None, _error("filter_value_invalid", str(key))

    group_by = params.get("group_by")
    if group_by is not None and (
        not isinstance(group_by, str) or group_by not in columns
    ):
        return None, _error("group_by_not_allowed", str(group_by))

    return (
        {
            "table": table,
            "app_label": app_label,
            "model_name": model_name,
            "column": column,
            "agg": agg,
            "filters": filters,
            "group_by": group_by,
        },
        None,
    )


def _aggregate_expression(agg: str, column: str):
    return {
        "sum": Sum(column),
        "avg": Avg(column),
        "count": Count(column),
        "min": Min(column),
        "max": Max(column),
    }[agg]


def _percentile(model, column: str, filters: dict, percentile: float) -> tuple:
    """Hitung percentile di PostgreSQL dengan batas 100k baris."""
    table_name = model._meta.db_table
    field = model._meta.get_field(column)
    column_name = field.column
    where_parts = []
    params: list[Any] = []
    for key, value in filters.items():
        parts = str(key).split("__", 1)
        base = parts[0]
        field_name = model._meta.get_field(base).column
        lookup = parts[1] if len(parts) > 1 else "exact"
        operator = {
            "gte": ">=",
            "lte": "<=",
            "gt": ">",
            "lt": "<",
            "exact": "=",
        }.get(lookup)
        if operator is None:
            raise ValueError(f"lookup tidak didukung: {lookup}")
        where_parts.append(f"{connection.ops.quote_name(field_name)} {operator} %s")
        params.append(value)

    where = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = (
        "SELECT percentile_cont(%s) WITHIN GROUP (ORDER BY {column}) "
        "FROM (SELECT {column} FROM {table}{where} LIMIT %s) AS sample"
    ).format(
        column=connection.ops.quote_name(column_name),
        table=connection.ops.quote_name(table_name),
        where=where,
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [percentile, *params, MAX_PERCENTILE_ROWS])
        row = cursor.fetchone()
    return (row[0] if row else None), model.objects.filter(**filters).count()


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Agregasi aman; tidak pernah mengembalikan baris mentah."""
    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses aggregator.")
    if method != "aggregate":
        return _error("method_tidak_dikenal", str(method))

    data = params or {}
    validated, error = _validate(data)
    if error is not None:
        return error

    try:
        model = django_apps.get_model(validated["app_label"], validated["model_name"])
        filters = validated["filters"]
        agg = validated["agg"]
        column = validated["column"]
        group_by = validated["group_by"]
        queryset = model.objects.filter(**filters)

        if agg in {"p50", "p90"}:
            if group_by:
                return _error(
                    "unsupported_group_by",
                    "Percentile belum mendukung group_by.",
                )
            result, count = _percentile(
                model, column, filters, 0.5 if agg == "p50" else 0.9
            )
            return {
                "ok": True,
                "agg": agg,
                "result": float(result or 0),
                "count": count,
            }

        expression = _aggregate_expression(agg, column)
        if group_by:
            grouped = (
                queryset.values(group_by)
                .annotate(value=expression)
                .order_by(group_by)[:100]
            )
            groups = [
                {
                    "key": row[group_by],
                    "value": float(row["value"] or 0),
                }
                for row in grouped
            ]
            total = queryset.aggregate(value=expression)["value"]
            return {
                "ok": True,
                "agg": agg,
                "result": float(total or 0),
                "count": int(queryset.count()),
                "group_by": group_by,
                "groups": groups,
            }

        value = queryset.aggregate(value=expression)["value"]
        return {
            "ok": True,
            "agg": agg,
            "result": float(value or 0),
            "count": int(queryset.count()),
        }
    except Exception as exc:  # noqa: BLE001 - fail-safe ke AI
        return _error("aggregation_error", type(exc).__name__)


def register(registry) -> None:
    registry.register("mcp-aggregator", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")

