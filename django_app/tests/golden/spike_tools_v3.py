"""Spike-3: 7 tool generik + label dimensi metrik memakai KODE (bukan id).

Hanya membungkus `spike_tools_v2` (throwaway). Satu-satunya perubahan perilaku:
`get_metric(group_by=work_center|line)` mengganti key/label id menjadi kode/nama.
"""

from __future__ import annotations

from typing import Any

from tests.golden import spike_tools_v2 as _v2

ENTITIES = _v2.ENTITIES
AGG_ENTITIES = _v2.AGG_ENTITIES
METRICS = _v2.METRICS
TOOLS_SCHEMA = _v2.TOOLS_SCHEMA

list_records = _v2.list_records
count_records = _v2.count_records
get_record = _v2.get_record
aggregate = _v2.aggregate
get_stock = _v2.get_stock
find_entity = _v2.find_entity


def get_metric(
    name: str,
    range: dict,
    group_by: str | None = None,
    filters: dict | None = None,
) -> dict:
    """`get_metric` v2 dengan label dimensi = kode/nama (bukan id)."""
    result = _v2.get_metric(name, range, group_by=group_by, filters=filters)
    rows = result.get("rows")
    if not isinstance(rows, list):
        return result

    dimension = result.get("group_by")
    if dimension in {"work_center", "line"}:
        from apps_industry.garment.models import ProductionLine, WorkCenter

        model = WorkCenter if dimension == "work_center" else ProductionLine
        ids: list[int] = []
        for row in rows:
            try:
                ids.append(int(str(row.get("key"))))
            except (TypeError, ValueError):
                continue
        objects = model.objects.in_bulk(ids)
        mapping = {
            str(pk): (obj.code if dimension == "work_center" else obj.name)
            for pk, obj in objects.items()
        }
        for row in rows:
            code = mapping.get(str(row.get("key")))
            if not code:
                continue
            row["key_id"] = row.get("key")
            row["label_id"] = row.get("label")
            row["key"] = code
            row["label"] = code
    return result


def execute(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch: get_metric memakai versi v3, sisanya v2."""
    if name == "get_metric":
        try:
            return {"ok": True, **get_metric(**arguments)}
        except Exception as exc:  # noqa: BLE001 - spike: error = hasil
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return _v2.execute(name, arguments)


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
