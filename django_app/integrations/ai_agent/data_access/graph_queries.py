"""Graph queries via PostgreSQL recursive CTE (TEMPORARY — ganti Neo4j).

Relasi: order → lines → work order → bundle → event → scrap.
Tidak butuh graph DB; cukup PostgreSQL yang sudah ada.
"""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.db.models import Count, Sum

__all__ = ("get_bundle_graph", "get_order_graph", "get_wc_graph")


def _bundle_ids_for_order(order_id: int) -> list[int]:
    """CTE rekursif untuk menelusuri order → line → WO → bundle."""
    sql = """
    WITH RECURSIVE order_bundles AS (
        SELECT b.id AS bundle_id
        FROM garment_bundle b
        JOIN garment_workorder wo ON b.work_order_id = wo.id
        JOIN garment_orderline ol ON wo.order_line_id = ol.id
        WHERE ol.order_id = %s
        UNION
        SELECT b.id AS bundle_id
        FROM garment_bundle b
        JOIN order_bundles ob ON b.work_order_id = (
            SELECT wo2.id
            FROM garment_workorder wo2
            JOIN garment_orderline ol2 ON wo2.order_line_id = ol2.id
            WHERE ol2.order_id = %s
            LIMIT 1
        )
    )
    SELECT DISTINCT bundle_id FROM order_bundles
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [order_id, order_id])
            return [int(row[0]) for row in cursor.fetchall()]
    except Exception:  # noqa: BLE001 - SQL vendor-specific; fallback ORM
        from apps_industry.garment.models import Bundle

        return list(
            Bundle.objects.filter(
                work_order__order_line__order_id=order_id
            ).values_list("id", flat=True)
        )


def _bundle_event_rows(bundle_ids: list[int], limit: int = 100) -> list[dict]:
    from apps_industry.garment.models import BundleEvent

    return list(
        BundleEvent.objects.filter(bundle_id__in=bundle_ids)
        .order_by("-ts")
        .values(
            "id",
            "bundle_id",
            "bundle__code",
            "event_type",
            "ts",
            "actor__username",
            "payload",
        )[:limit]
    )


def _scrap_rows(bundle_ids: list[int], limit: int = 100) -> list[dict]:
    from apps_industry.garment.models import ScrapAccumulator

    return list(
        ScrapAccumulator.objects.filter(bundle_id__in=bundle_ids)
        .values(
            "id",
            "bundle_id",
            "bundle__code",
            "work_center__code",
            "qty",
            "rework_qty",
            "reason",
            "created_at",
        )
        .order_by("-created_at")[:limit]
    )


def get_order_graph(order_id: int) -> dict[str, Any]:
    """Order → lines → WO → bundles → events → scrap (recursive CTE)."""
    from apps_industry.garment.models import Bundle, Order, OrderLine

    order = (
        Order.objects.filter(pk=order_id)
        .values("id", "code", "state", "customer__name")
        .first()
    )
    if order is None:
        return {"found": False, "order_id": order_id, "nodes": [], "edges": []}

    lines = list(
        OrderLine.objects.filter(order_id=order_id).values(
            "id", "product__name", "product__code", "qty", "tag"
        )
    )
    bundle_ids = _bundle_ids_for_order(order_id)
    bundles = list(
        Bundle.objects.filter(pk__in=bundle_ids).values(
            "id",
            "code",
            "qty",
            "qty_done",
            "state",
            "current_work_center__code",
            "production_line__code",
            "work_order__code",
        )
    )
    events = _bundle_event_rows(bundle_ids)
    scrap = _scrap_rows(bundle_ids)

    nodes: list[dict] = [{"type": "order", "id": order["id"], "label": order["code"]}]
    nodes += [
        {
            "type": "line",
            "id": row["id"],
            "label": row["product__name"] or row["product__code"],
        }
        for row in lines
    ]
    nodes += [
        {"type": "bundle", "id": row["id"], "label": row["code"]} for row in bundles
    ]
    nodes += [
        {
            "type": "work_center",
            "id": row["current_work_center__code"],
            "label": row["current_work_center__code"],
        }
        for row in bundles
        if row["current_work_center__code"]
    ]

    return {
        "found": True,
        "order_id": order_id,
        "order": order,
        "lines": lines,
        "bundles": bundles,
        "events": events,
        "scrap": scrap,
        "nodes": nodes,
        "summary": {
            "line_count": len(lines),
            "bundle_count": len(bundles),
            "event_count": len(events),
            "scrap_qty": float(sum(row["qty"] or 0 for row in scrap)),
            "rework_qty": float(sum(row["rework_qty"] or 0 for row in scrap)),
        },
    }

def get_bundle_graph(bundle_id: int) -> dict[str, Any]:
    """Bundle → WO → order → customer + event/scrap terbaru."""
    from apps_industry.garment.models import Bundle

    bundle = (
        Bundle.objects.filter(pk=bundle_id)
        .values(
            "id",
            "code",
            "qty",
            "qty_done",
            "state",
            "updated_at",
            "work_order__id",
            "work_order__code",
            "work_order__order_line__order__id",
            "work_order__order_line__order__code",
            "work_order__order_line__order__customer__name",
            "current_work_center__code",
            "production_line__code",
        )
        .first()
    )
    if bundle is None:
        return {"found": False, "bundle_id": bundle_id, "events": [], "scrap": []}

    events = _bundle_event_rows([bundle_id])
    scrap = _scrap_rows([bundle_id])

    return {
        "found": True,
        "bundle_id": bundle_id,
        "bundle": bundle,
        "order": {
            "id": bundle["work_order__order_line__order__id"],
            "code": bundle["work_order__order_line__order__code"],
            "customer": bundle["work_order__order_line__order__customer__name"],
        },
        "work_order": {
            "id": bundle["work_order__id"],
            "code": bundle["work_order__code"],
        },
        "events": events,
        "scrap": scrap,
        "summary": {
            "event_count": len(events),
            "scrap_qty": float(sum(row["qty"] or 0 for row in scrap)),
        },
    }


def get_wc_graph(wc_id: int) -> dict[str, Any]:
    """Work center → bundles → operators (aktor event) → scrap."""
    from apps_industry.garment.models import (
        Bundle,
        BundleEvent,
        ScrapAccumulator,
        WorkCenter,
    )

    work_center = (
        WorkCenter.objects.filter(pk=wc_id)
        .values("id", "code", "name", "capacity_per_hour")
        .first()
    )
    if work_center is None:
        return {
            "found": False,
            "work_center_id": wc_id,
            "bundles": [],
            "operators": [],
        }

    bundles = list(
        Bundle.objects.filter(current_work_center_id=wc_id)
        .exclude(state__in=["DONE", "CANCELLED"])
        .values("id", "code", "qty", "state", "production_line__code")
    )
    bundle_ids = [row["id"] for row in bundles]

    operators = list(
        BundleEvent.objects.filter(bundle_id__in=bundle_ids, actor__isnull=False)
        .values("actor_id", "actor__username")
        .annotate(events=Count("id"))
        .order_by("-events")
    )
    scrap = list(
        ScrapAccumulator.objects.filter(work_center_id=wc_id)
        .values("id", "bundle_id", "bundle__code", "qty", "rework_qty", "reason")
        .order_by("-created_at")[:100]
    )
    total_scrap = ScrapAccumulator.objects.filter(work_center_id=wc_id).aggregate(
        total=Sum("qty")
    )["total"]

    return {
        "found": True,
        "work_center_id": wc_id,
        "work_center": work_center,
        "bundles": bundles,
        "operators": operators,
        "scrap": scrap,
        "summary": {
            "buffer_length": len(bundles),
            "operator_count": len(operators),
            "scrap_qty": float(total_scrap or 0),
        },
    }

