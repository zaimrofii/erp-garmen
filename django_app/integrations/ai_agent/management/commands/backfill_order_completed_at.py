"""Backfill `Order.completed_at` untuk order DONE lama (FIX #12)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps_industry.garment.models import BundleEvent, Order


class Command(BaseCommand):
    help = "Isi completed_at order DONE dari BUNDLE_FINISH terakhir/deadline."

    def handle(self, *args, **options):
        updated = 0
        skipped = 0
        orders = Order.objects.filter(state="DONE", completed_at__isnull=True)
        for order in orders.iterator():
            finish = (
                BundleEvent.objects.filter(
                    bundle__work_order__order_line__order=order,
                    event_type="BUNDLE_FINISH",
                )
                .order_by("-ts")
                .first()
            )
            completed_at = finish.ts if finish else order.deadline
            if not completed_at:
                skipped += 1
                continue
            Order.objects.filter(pk=order.pk).update(completed_at=completed_at)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Order completed_at backfill: {updated} updated, {skipped} skipped."
            )
        )
