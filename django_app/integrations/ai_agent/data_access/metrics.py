"""Agregat lintas entity — nama ikut di-JOIN, tidak ada ID mentah saja."""

from __future__ import annotations

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import ExtractHour

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

    def customer_total_spend_by_id(self, customer_id: int) -> float:
        """Total belanja customer = sum(qty × price_unit) OrderLine."""
        value = OrderLine.objects.filter(order__customer_id=customer_id).aggregate(
            total=Sum(
                F("qty") * F("price_unit"),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        return float(value or 0)

    def customer_detail(self, customer_id: int) -> dict | None:
        """Detail customer + jumlah order untuk follow-up."""
        from master.models import Partner

        partner = Partner.objects.filter(pk=customer_id).first()
        if partner is None:
            return None
        return {
            "id": partner.pk,
            "code": partner.code,
            "name": partner.name,
            "city": partner.city or "",
            "order_count": Order.objects.filter(customer_id=customer_id).count(),
            "total_spend": self.customer_total_spend_by_id(customer_id),
        }

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
        """Bundle di WC tertentu via current_work_center + riwayat event."""
        event_bundle_ids = list(
            BundleEvent.objects.filter(payload__work_center_code=wc_code)
            .values_list("bundle_id", flat=True)
            .distinct()
        )
        current_bundle_ids = list(
            Bundle.objects.filter(current_work_center__code=wc_code).values_list(
                "id", flat=True
            )
        )
        bundle_ids = list(dict.fromkeys(event_bundle_ids + current_bundle_ids))[:limit]
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
            duration_hours = 0.0
            if len(events) >= 2:
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


    def quality_by_operator(self) -> list[dict]:
        """SCRAP/REWORK event per operator (SQL GROUP BY actor)."""
        rows = (
            BundleEvent.objects.filter(
                event_type__in=["SCRAP", "REWORK"], actor__isnull=False
            )
            .values("actor_id", "actor__username")
            .annotate(
                scrap_events=Count("id", filter=Q(event_type="SCRAP")),
                rework_events=Count("id", filter=Q(event_type="REWORK")),
                total_events=Count("id"),
            )
            .order_by("-total_events")
        )
        return [
            {
                "operator_id": row["actor_id"],
                "operator": row["actor__username"],
                "scrap_events": int(row["scrap_events"] or 0),
                "rework_events": int(row["rework_events"] or 0),
                "total_events": int(row["total_events"] or 0),
            }
            for row in rows
        ]

    def quality_by_shift(self) -> list[dict]:
        """Scrap/rework per shift (1: <14, 2: 14-22, 3: lainnya)."""
        rows = (
            ScrapAccumulator.objects.annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(scrap=Sum("qty"), rework=Sum("rework_qty"))
        )
        buckets = {
            1: {"shift": 1, "scrap_qty": 0.0, "rework_qty": 0.0},
            2: {"shift": 2, "scrap_qty": 0.0, "rework_qty": 0.0},
            3: {"shift": 3, "scrap_qty": 0.0, "rework_qty": 0.0},
        }
        for row in rows:
            hour = int(row["hour"] or 0)
            shift = 1 if hour < 14 else (2 if hour < 22 else 3)
            buckets[shift]["scrap_qty"] += float(row["scrap"] or 0)
            buckets[shift]["rework_qty"] += float(row["rework"] or 0)
        return [buckets[key] for key in sorted(buckets)]

    def quality_by_wc(self) -> list[dict]:
        """Scrap/rework per work center (alias terstruktur)."""
        return [
            {
                "work_center_id": row["work_center_id"],
                "work_center": row["work_center_code"],
                "scrap_qty": row["total_scrap"],
                "rework_qty": row["total_rework"],
            }
            for row in self.metrics_by_wc()
        ]

    def quality_correlation(self) -> dict:
        """Korelasi Pearson scrap vs rework event antar operator."""
        rows = self.quality_by_operator()
        xs = [float(row["scrap_events"]) for row in rows]
        ys = [float(row["rework_events"]) for row in rows]
        coefficient = _pearson(xs, ys)

        if coefficient is None:
            interpretation = "data belum cukup"
        elif coefficient >= 0.5:
            interpretation = "positif kuat: operator dengan scrap tinggi juga rework tinggi"
        elif coefficient <= -0.5:
            interpretation = "negatif kuat: scrap dan rework bergerak berlawanan"
        else:
            interpretation = "lemah/tidak signifikan"

        return {
            "r": coefficient,
            "n": len(rows),
            "interpretation": interpretation,
            "method": "pearson",
        }

    def anomaly_snapshot(self) -> dict:
        """Paket data untuk anomaly explainer (operator/shift/WC)."""
        return {
            "by_operator": self.quality_by_operator(),
            "by_shift": self.quality_by_shift(),
            "by_wc": self.quality_by_wc(),
            "correlation": self.quality_correlation(),
        }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Koefisien Pearson PURE; None bila data < 2 atau variansi nol."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    denom_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return round(numerator / (denom_x * denom_y), 4)


__all__ = ("MetricsRepository",)

