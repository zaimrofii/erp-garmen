"""Agregat lintas entity — nama ikut di-JOIN, tidak ada ID mentah saja."""

from __future__ import annotations

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    OrderLine,
    ProductionLine,
    ScrapAccumulator,
    WorkCenter,
)


class MetricsRepository:
    def customer_orders(self, limit: int = 10) -> list[dict]:
        amount = ExpressionWrapper(
            F("lines__qty") * F("lines__price_unit"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        rows = (
            Order.objects.values(
                "customer_id",
                "customer__name",
                "customer__code",
            )
            .annotate(
                order_count=Count("id", distinct=True),
                total_qty=Sum("lines__qty"),
                amount=Sum(amount),
            )
            .order_by("-order_count")[:limit]
        )
        result = []
        for row in rows:
            name = row["customer__name"] or ""
            result.append(
                {
                    **row,
                    "customer": name,
                    "order_count": int(row["order_count"] or 0),
                    "total_qty": float(row["total_qty"] or 0),
                    "amount": float(row["amount"] or 0),
                }
            )
        return result

    def product_production(self, limit: int = 10) -> list[dict]:
        rows = (
            Bundle.objects.filter(state="DONE")
            .values(
                "work_order__order_line__product_id",
                "work_order__order_line__product__name",
                "work_order__order_line__product__code",
            )
            .annotate(total_qty=Sum("qty_done"))
            .order_by("-total_qty")[:limit]
        )
        result = []
        for row in rows:
            product_id = row["work_order__order_line__product_id"]
            result.append(
                {
                    **row,
                    "product_id": product_id,
                    "product": row["work_order__order_line__product__name"] or "",
                    "product_code": row["work_order__order_line__product__code"],
                    "qty_done": float(row["total_qty"] or 0),
                }
            )
        return result

    def metrics_by_wc(self) -> list[dict]:
        work_centers = {
            wc.id: {"name": wc.name, "code": wc.code}
            for wc in WorkCenter.objects.all()
        }
        rows = (
            ScrapAccumulator.objects.values("work_center_id")
            .annotate(total_scrap=Sum("qty"), total_rework=Sum("rework_qty"))
            .order_by("-total_scrap")
        )
        return [
            {
                "work_center_id": row["work_center_id"],
                "work_center_name": work_centers.get(row["work_center_id"], {}).get(
                    "name"
                ),
                "work_center_code": work_centers.get(row["work_center_id"], {}).get(
                    "code"
                ),
                "total_scrap": float(row["total_scrap"] or 0),
                "total_rework": float(row["total_rework"] or 0),
            }
            for row in rows
        ]

    def metrics_by_line(self) -> list[dict]:
        lines = {line.id: line.name for line in ProductionLine.objects.all()}
        rows = (
            Bundle.objects.exclude(state__in=["DONE", "CANCELLED"])
            .values("production_line_id")
            .annotate(bundle_count=Count("id"))
            .order_by("-bundle_count")
        )
        return [
            {
                "line_id": row["production_line_id"],
                "production_line_id": row["production_line_id"],
                "line_name": lines.get(row["production_line_id"]),
                "bundle_count": int(row["bundle_count"] or 0),
            }
            for row in rows
        ]

    def bundles_by_order(self, limit: int = 10) -> list[dict]:
        return list(
            Bundle.objects.values(
                "work_order__order_line__order__code",
                "work_order__order_line__order__customer__name",
            )
            .annotate(bundle_count=Count("id"))
            .order_by("-bundle_count")[:limit]
        )

    def scrap_by_customer(self, limit: int = 10) -> list[dict]:
        return list(
            ScrapAccumulator.objects.values(
                "bundle__work_order__order_line__order__customer__name",
                "bundle__work_order__order_line__order__customer__code",
            )
            .annotate(
                total_scrap=Sum("qty"),
                total_rework=Sum("rework_qty"),
            )
            .order_by("-total_scrap")[:limit]
        )

    def customer_total_spend(self, limit: int = 10) -> list[dict]:
        return list(
            OrderLine.objects.values(
                "order__customer__name",
                "order__customer__code",
            )
            .annotate(
                total_spend=Sum(
                    F("qty") * F("price_unit"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
            .order_by("-total_spend")[:limit]
        )

    def order_late_percentage(self) -> dict:
        total = Order.objects.filter(completed_at__isnull=False).count()
        late = Order.objects.filter(
            completed_at__isnull=False,
            completed_at__gt=F("deadline"),
        ).count()
        return {
            "total_completed": total,
            "late_count": late,
            "on_time_count": total - late,
            "late_percentage": round(late / total * 100, 2) if total else 0,
        }

    def bundles_in_work_center(self, wc_code: str, limit: int = 20) -> list[dict]:
        """Bundle yang pernah berada di WC tertentu, via BundleEvent.payload."""
        bundle_ids = list(
            BundleEvent.objects.filter(payload__work_center_code=wc_code)
            .values_list("bundle_id", flat=True)
            .distinct()[:limit]
        )
        if not bundle_ids:
            return []

        bundles = Bundle.objects.filter(id__in=bundle_ids).select_related(
            "work_order__order_line__product",
            "work_order__order_line__order__customer",
        )
        result: list[dict] = []
        for bundle in bundles:
            events = list(
                BundleEvent.objects.filter(
                    bundle=bundle, payload__work_center_code=wc_code
                ).order_by("ts")
            )
            if len(events) < 2:
                continue
            duration_hours = (
                events[-1].ts - events[0].ts
            ).total_seconds() / 3600
            order_line = bundle.work_order.order_line
            order = order_line.order
            result.append(
                {
                    "bundle_code": bundle.code,
                    "product_name": getattr(order_line.product, "name", None),
                    "order_code": order.code,
                    "customer_name": getattr(order.customer, "name", None),
                    "duration_hours": round(duration_hours, 2),
                    "events_count": len(events),
                }
            )
        return sorted(result, key=lambda row: -row["duration_hours"])[:limit]


__all__ = ("MetricsRepository",)
