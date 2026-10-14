"""ScrapAccumulatorService — akumulasi scrap / rework / end-loss (Sprint 2.3).

Blueprint memisahkan tiga jenis kehilangan supaya bisa dianalisis terpisah:

  * ``qty``          — scrap (dibuang);
  * ``rework_qty``   — masuk loop rework (masih bisa diselamatkan);
  * ``end_loss_qty`` — kehilangan di akhir (end-loss).

Baris diakumulasi per **(work_center, bundle)** memakai `get_or_create` +
`F()` expression supaya penulisan paralel dari beberapa perangkat tidak membuat
baris dobel atau kehilangan penambahan (read-modify-write).

Service sinkron murni: tidak publish event (itu Fase 3 saat endpoint memanggil).
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Count, F, Sum

from apps_industry.garment.models import Bundle, ScrapAccumulator, WorkCenter
from apps_industry.garment.services.exceptions import ScrapAccumulatorError

logger = logging.getLogger(__name__)

QTY_FIELD = "qty"
REWORK_FIELD = "rework_qty"
END_LOSS_FIELD = "end_loss_qty"


class ScrapAccumulatorService:
    """Akumulator scrap per work center (stateless)."""

    ACCUMULATED_FIELDS = (QTY_FIELD, REWORK_FIELD, END_LOSS_FIELD)

    # ------------------------------------------------------------------ writes
    def record_scrap(
        self, bundle: Bundle, work_center: WorkCenter, qty, reason: str = ""
    ) -> ScrapAccumulator:
        """Tambah `qty` scrap untuk (work_center, bundle)."""
        return self._accumulate(bundle, work_center, QTY_FIELD, qty, reason)

    def record_rework(
        self, bundle: Bundle, work_center: WorkCenter, qty
    ) -> ScrapAccumulator:
        """Tambah `qty` rework untuk (work_center, bundle)."""
        return self._accumulate(bundle, work_center, REWORK_FIELD, qty)

    def record_end_loss(
        self, bundle: Bundle, work_center: WorkCenter, qty, reason: str = ""
    ) -> ScrapAccumulator:
        """Tambah `qty` end-loss untuk (work_center, bundle)."""
        return self._accumulate(bundle, work_center, END_LOSS_FIELD, qty, reason)

    # ------------------------------------------------------------------- reads
    def get_bundle_scrap(self, bundle: Bundle) -> ScrapAccumulator | None:
        """Baris akumulasi bundle; kalau ada beberapa WC, ambil yang terakhir diubah."""
        if bundle is None:
            raise ScrapAccumulatorError("bundle wajib diisi.")
        return (
            ScrapAccumulator.objects.filter(bundle=bundle)
            .order_by("-updated_at", "-pk")
            .first()
        )

    def get_summary(self, work_center: WorkCenter) -> dict:
        """Ringkasan scrap satu WC (total qty/rework/end-loss + jumlah bundle)."""
        if work_center is None:
            raise ScrapAccumulatorError("work_center wajib diisi.")

        rows = ScrapAccumulator.objects.filter(work_center=work_center)
        totals = rows.aggregate(
            total_qty=Sum(QTY_FIELD),
            total_rework=Sum(REWORK_FIELD),
            total_end_loss=Sum(END_LOSS_FIELD),
        )
        return {
            "work_center": work_center.code,
            "total_qty": totals["total_qty"] or 0,
            "total_rework_qty": totals["total_rework"] or 0,
            "total_end_loss_qty": totals["total_end_loss"] or 0,
            "bundle_count": rows.exclude(bundle__isnull=True)
            .values("bundle")
            .distinct()
            .count(),
            "entries": rows.count(),
        }

    def get_top_scrap_work_centers(self, limit: int = 5) -> list[dict]:
        """Work center dengan total scrap tertinggi (desc, tie-break kode WC)."""
        try:
            limit_int = int(limit)
        except (TypeError, ValueError) as exc:
            raise ScrapAccumulatorError("limit harus bilangan bulat > 0.") from exc
        if limit_int <= 0:
            raise ScrapAccumulatorError("limit harus bilangan bulat > 0.")

        rows = (
            ScrapAccumulator.objects.values("work_center__code")
            .annotate(
                total_qty=Sum(QTY_FIELD),
                total_rework=Sum(REWORK_FIELD),
                total_end_loss=Sum(END_LOSS_FIELD),
                entries=Count("pk"),
            )
            .order_by("-total_qty", "work_center__code")[:limit_int]
        )
        return [
            {
                "work_center": row["work_center__code"],
                "total_qty": row["total_qty"] or 0,
                "total_rework_qty": row["total_rework"] or 0,
                "total_end_loss_qty": row["total_end_loss"] or 0,
                "entries": row["entries"],
            }
            for row in rows
        ]

    # ---------------------------------------------------------------- internal
    def _accumulate(
        self,
        bundle: Bundle,
        work_center: WorkCenter,
        field: str,
        qty,
        reason: str = "",
    ) -> ScrapAccumulator:
        """Tambah `qty` ke `field` pada baris (work_center, bundle)."""
        if field not in self.ACCUMULATED_FIELDS:
            raise ScrapAccumulatorError(f"field akumulasi '{field}' tidak dikenal.")
        qty_int = self._validate(bundle, work_center, qty)

        with transaction.atomic():
            row = (
                ScrapAccumulator.objects.select_for_update()
                .filter(work_center=work_center, bundle=bundle)
                .first()
            )
            if row is None:
                return ScrapAccumulator.objects.create(
                    work_center=work_center,
                    bundle=bundle,
                    reason=reason or "",
                    **{field: qty_int},
                )

            updates = {field: F(field) + qty_int}
            if reason:
                updates["reason"] = reason
            ScrapAccumulator.objects.filter(pk=row.pk).update(**updates)

        row.refresh_from_db()
        logger.info(
            "scrap accumulator: %s +%s pada %s (bundle %s).",
            field,
            qty_int,
            work_center.code,
            bundle.code,
        )
        return row

    @staticmethod
    def _validate(bundle: Bundle, work_center: WorkCenter, qty) -> int:
        """bundle & work_center wajib; qty harus bilangan bulat > 0."""
        if bundle is None or bundle.pk is None:
            raise ScrapAccumulatorError("bundle wajib diisi dan sudah tersimpan.")
        if work_center is None:
            raise ScrapAccumulatorError("work_center wajib diisi.")
        try:
            qty_int = int(qty)
        except (TypeError, ValueError) as exc:
            raise ScrapAccumulatorError("qty harus bilangan bulat > 0.") from exc
        if qty_int <= 0:
            raise ScrapAccumulatorError("qty harus bilangan bulat > 0.")
        return qty_int
