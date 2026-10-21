"""Backfill `BundleEvent.payload.work_center_code` untuk data lama (FIX #10)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps_industry.garment.models import BundleEvent, ScrapAccumulator


class Command(BaseCommand):
    help = "Isi payload.work_center_code pada BundleEvent lama (idempoten)."

    def _infer(self, event: BundleEvent) -> str | None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_type = event.event_type

        if event_type in {"QC_FAIL", "QC_PASS"}:
            return payload.get("work_center_code") or "QC-1"
        if event_type == "BUNDLE_FINISH":
            return payload.get("work_center_code") or "PACKING"
        if event_type == "BUNDLE_START":
            return payload.get("work_center_code") or "CUTTING"
        if event_type in {"SCRAP", "SCRAP_RECORDED"}:
            scrap = (
                ScrapAccumulator.objects.filter(bundle=event.bundle)
                .select_related("work_center")
                .order_by("-created_at")
                .first()
            )
            if scrap and scrap.work_center:
                return scrap.work_center.code
            return "SEWING-2"
        if event_type == "BUNDLE_STATE_CHANGED":
            state_to = str(payload.get("state_to") or "").upper()
            mapping = {
                "CUTTING": "CUTTING",
                "SEWING": "SEWING-1",
                "QC": "QC-1",
                "PACKING": "PACKING",
                "DONE": "PACKING",
            }
            return mapping.get(state_to)
        if event_type == "REWORK":
            return payload.get("work_center_code") or "SEWING-2"

        bundle = event.bundle
        if bundle and bundle.current_work_center_id:
            return bundle.current_work_center.code
        return None

    def handle(self, *args, **options):
        updated = 0
        skipped = 0
        for event in BundleEvent.objects.select_related(
            "bundle__current_work_center"
        ).iterator():
            payload = event.payload if isinstance(event.payload, dict) else {}
            if payload.get("work_center_code"):
                skipped += 1
                continue
            wc_code = self._infer(event)
            if not wc_code:
                skipped += 1
                continue
            BundleEvent.objects.filter(pk=event.pk).update(
                payload={**payload, "work_center_code": wc_code}
            )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"BundleEvent backfill: {updated} updated, {skipped} skipped."
            )
        )
