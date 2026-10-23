"""Spike validasi: desain 7 tool generik (throwaway, calon desain Fase 1).

Perbaikan vs spike-3:
  * get_metric → envelope berlabel `stats` (avg/latest/min/max/count/sum).
  * order (list/get) → field turunan is_late/days_late/days_remaining.
  * date_from/date_to di list/count/aggregate (default 7 hari terakhir).
  * find_entity → {matches, ambiguous, count}.
  * get_stock → envelope lengkap (product_name, uom, location_code, as_of, warnings).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.utils import timezone

from tests.golden import spike_tools_v2 as _v2

ENTITIES = _v2.ENTITIES
AGG_ENTITIES = _v2.AGG_ENTITIES
METRICS = _v2.METRICS
MAX_LIMIT = _v2.MAX_LIMIT


def _build_schema() -> list[dict]:
    """Salin schema v2 lalu tambahkan date_from/date_to + deskripsi envelope."""
    import copy

    schema = copy.deepcopy(_v2.TOOLS_SCHEMA)
    date_props = {
        "date_from": {
            "type": "string",
            "description": "ISO date (YYYY-MM-DD). Kosongkan untuk snapshot/all-time.",
        },
        "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
    }
    for tool in schema:
        function = tool["function"]
        name = function["name"]
        props = function["parameters"]["properties"]
        if name in {"list_records", "count_records", "aggregate"}:
            props.update(copy.deepcopy(date_props))
            function["description"] += (
                " Isi date_from/date_to hanya bila pertanyaan berperiode"
                " (minggu ini/bulan ini); kosong = seluruh periode."
            )
        if name == "list_records":
            function["description"] += (
                " Untuk entity=order, setiap baris memuat is_late, days_late,"
                " days_remaining (dihitung sistem)."
            )
        if name == "get_metric":
            function["description"] += (
                " Mengembalikan stats {avg, latest, min, max, count, sum} + series;"
                " pakai stats.avg untuk pertanyaan rata-rata."
            )
        if name == "get_stock":
            function["description"] += (
                " Envelope: product_code, product_name, quantity, reserved, available, uom,"
                " location_code, as_of, warnings."
            )
        if name == "find_entity":
            function["description"] += (
                " Envelope: {matches: [{id, code, name}], ambiguous, count}."
            )
    return schema


TOOLS_SCHEMA = _build_schema()

DATE_FIELD = {"order": "created_at", "bundle": "created_at", "work_order": "created_at"}


def _today() -> date:
    return timezone.localdate()


def _date_kwargs(entity: str, date_from: str | None, date_to: str | None) -> dict:
    """Filter tanggal eksplisit. Tanpa date_from/date_to → tanpa filter (snapshot).

    Catatan: default 7 hari TIDAK dipaksakan karena akan merusak pertanyaan
    snapshot (mis. "bundle di SEWING-2 sekarang"); LLM mengisi tanggal saat
    pertanyaan memang berperiode ("minggu ini", "bulan ini").
    """
    field = DATE_FIELD.get(entity)
    if field is None or (not date_from and not date_to):
        return {}
    end = date.fromisoformat(date_to) if date_to else _today()
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=6)
    return {f"{field}__date__gte": start, f"{field}__date__lte": end}


def _order_derived(record: dict) -> dict:
    deadline = record.get("deadline")
    completed = record.get("completed_at")
    now = timezone.now()
    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline)
        except ValueError:
            deadline = None
    if isinstance(completed, str):
        try:
            completed = datetime.fromisoformat(completed)
        except ValueError:
            completed = None
    is_late = bool(deadline and completed and completed > deadline)
    days_late = (completed - deadline).days if is_late else 0
    days_remaining = None
    if deadline and not completed:
        days_remaining = (deadline - now).days
    record["is_late"] = is_late
    record["days_late"] = days_late
    record["days_remaining"] = days_remaining
    return record


def list_records(
    entity: str,
    filters: dict | None = None,
    sort: str = "",
    limit: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    repo = _v2._repo(entity)
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    criteria = _v2._clean_filters(entity, filters)
    criteria.update(_date_kwargs(entity, date_from, date_to))
    qs = repo.model.objects.filter(**criteria)
    qs = qs.order_by(str(sort)) if sort else qs.order_by(*repo.order_by)
    rows = [repo._serialize(obj) for obj in qs[:limit]]
    if entity == "order":
        rows = [_order_derived(row) for row in rows]
    return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= limit}


def count_records(
    entity: str,
    filters: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    model = _v2._model(entity)
    criteria = _v2._clean_filters(entity, filters)
    criteria.update(_date_kwargs(entity, date_from, date_to))
    return {"count": model.objects.filter(**criteria).count()}


def get_record(entity: str, id_or_code: str, include: list[str] | None = None) -> dict:
    result = _v2.get_record(entity, id_or_code, include)
    record = result.get("record")
    if record and str(entity).lower() == "order":
        _order_derived(record)
    return result


def aggregate(
    entity: str,
    field: str,
    op: str,
    group_by: str | None = None,
    filters: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    from django.db.models import Avg, Count, Max, Min, Sum

    entity = str(entity or "").strip().lower()
    model = _v2._model(entity)
    op = str(op or "").strip().lower()
    field = str(field or "").strip()
    criteria = _v2._clean_filters(entity, filters)
    criteria.update(_date_kwargs(entity, date_from, date_to))
    qs = model.objects.filter(**criteria)

    alias = f"{op}_{field}"
    if op == "count_distinct":
        expression = Count(field, distinct=True)
    elif op == "count":
        expression = Count("id")
    else:
        expression = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[op](field)

    if group_by:
        path = _v2.GROUP_ALIASES.get(entity, {}).get(str(group_by), str(group_by))
        rows = list(
            qs.values(path).annotate(**{alias: expression}).order_by(f"-{alias}")[:MAX_LIMIT]
        )
    else:
        rows = [qs.aggregate(**{alias: expression})]
    return {"rows": rows, "row_count": len(rows), "op": op, "field": field, "group_by": group_by}


def get_metric(
    name: str,
    range: dict | None = None,
    group_by: str | None = None,
    filters: dict | None = None,
) -> dict:
    from integrations.analytics.core import registry as analytics_registry

    if name not in METRICS:
        return {"error": "metric_not_available", "detail": f"metrik {name!r} tidak terdaftar"}
    if str(group_by or "").lower() == "operator":
        return {"error": "metric_not_available", "detail": "tidak ada metrik per operator"}

    end = _today()
    start = end - timedelta(days=6)
    if isinstance(range, dict):
        try:
            start = date.fromisoformat(str(range.get("from") or start))
            end = date.fromisoformat(str(range.get("to") or end))
        except ValueError:
            pass

    metric = analytics_registry.get_metric(name)
    dims = list(getattr(metric, "dimensions", []) or [])
    requested = str(group_by or "period")
    chosen = requested if requested in dims else "period"
    series = metric.compute(
        {
            "group_by": chosen,
            "granularity": "day",
            "date_from": start,
            "date_to": end,
            **(filters or {}),
        }
    )[:MAX_LIMIT]

    values = [
        float(row["value"])
        for row in series
        if isinstance(row.get("value"), (int, float))
    ]
    warnings: list[str] = []
    if not values:
        warnings.append("no_data_in_period")
    stats = {
        "avg": round(sum(values) / len(values), 6) if values else None,
        "latest": values[-1] if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "count": len(values),
        "sum": round(sum(values), 6) if values else 0,
    }
    return {
        "metric": name,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "group_by": chosen,
        "stats": stats,
        "series": series,
        "unit": getattr(metric, "unit", ""),
        "warnings": warnings,
    }


def get_stock(product_code: str, location_code: str | None = None) -> dict:
    result = _v2.get_stock(product_code, location_code)
    if result.get("error"):
        return result
    from master.models import Product

    product = Product.objects.filter(code__iexact=str(product_code)).first()
    result.update(
        {
            "product_name": product.name if product else None,
            "uom": getattr(getattr(product, "uom", None), "name", None),
            "location_code": location_code or "internal",
            "as_of": timezone.now().isoformat(),
            "warnings": [] if result.get("row_count") else ["no_quant_found"],
        }
    )
    return result


def find_entity(entity: str, text: str) -> dict:
    result = _v2.find_entity(entity, text)
    if result.get("error") == "not_found":
        return {"matches": [], "ambiguous": False, "count": 0}
    matches = result.get("candidates") or []
    return {"matches": matches, "ambiguous": len(matches) > 1, "count": len(matches)}


def execute(name: str, arguments: dict[str, Any]) -> dict:
    try:
        if name == "list_records":
            return {"ok": True, **list_records(**arguments)}
        if name == "count_records":
            return {"ok": True, **count_records(**arguments)}
        if name == "get_record":
            return {"ok": True, **get_record(**arguments)}
        if name == "aggregate":
            return {"ok": True, **aggregate(**arguments)}
        if name == "get_metric":
            return {"ok": True, **get_metric(**arguments)}
        if name == "get_stock":
            return {"ok": True, **get_stock(**arguments)}
        if name == "find_entity":
            return {"ok": True, **find_entity(**arguments)}
        return {"ok": False, "error": f"tool tidak dikenal: {name}"}
    except Exception as exc:  # noqa: BLE001 - spike: error = hasil
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = (
    "AGG_ENTITIES",
    "ENTITIES",
    "METRICS",
    "TOOLS_SCHEMA",
    "aggregate",
    "count_records",
    "execute",
    "find_entity",
    "get_metric",
    "get_record",
    "get_stock",
    "list_records",
)

