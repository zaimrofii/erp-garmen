"""CapabilityAllocator — pemilihan line produksi berbasis kapabilitas (Sprint 2.2).

Sebuah `ProductionLine` dianggap "mampu" mengerjakan routing kalau **semua**
work center yang dibutuhkan routing (`ProcessRouting.steps.work_center`) ada di
`line.work_centers` — yaitu line tersebut **superset** dari kebutuhan. Dari line
yang mampu, dipilih yang **paling sedikit work center** (paling spesifik) supaya
line besar tidak dipakai untuk pekerjaan kecil.

Fail-closed: routing yang belum punya step ber-work center dianggap
kapabilitasnya tidak diketahui -> `allocate()` mengembalikan `None` (service
tidak menebak line).

Read-only: service tidak mengubah apa pun (`bundle.production_line` di-set oleh
pemanggil, Fase 3). Parameter `work_order` disimpan di signature untuk filter
lanjutan (kapasitas/prioritas line) pada fase berikutnya — alokasi saat ini
murni ditentukan routing + work center line.
"""

from __future__ import annotations

import logging

from apps_industry.garment.models import ProcessRouting, ProductionLine, WorkOrder
from apps_industry.garment.services.exceptions import CapabilityAllocatorError

logger = logging.getLogger(__name__)


class CapabilityAllocator:
    """Alokasi line produksi berbasis superset work center (stateless)."""

    @staticmethod
    def required_work_centers(routing: ProcessRouting) -> set[int]:
        """Id work center yang dibutuhkan routing (dari step-nya)."""
        if routing is None:
            raise CapabilityAllocatorError("routing wajib diisi.")
        return set(
            routing.steps.exclude(work_center__isnull=True).values_list(
                "work_center_id", flat=True
            )
        )

    def candidates(
        self, work_order: WorkOrder, routing: ProcessRouting
    ) -> list[ProductionLine]:
        """Semua line aktif yang mampu, urut dari paling spesifik (WC paling sedikit)."""
        if work_order is None:
            raise CapabilityAllocatorError("work_order wajib diisi.")

        required = self.required_work_centers(routing)
        if not required:
            logger.info(
                "routing '%s' belum punya step ber-work center; tidak ada kandidat line.",
                routing.code,
            )
            return []

        lines = (
            ProductionLine.objects.filter(is_active=True, work_centers__in=required)
            .distinct()
            .prefetch_related("work_centers")
        )

        capable: list[tuple[int, ProductionLine]] = []
        for line in lines:
            wc_ids = {work_center.pk for work_center in line.work_centers.all()}
            if wc_ids >= required:  # superset: line punya semua WC yang dibutuhkan
                capable.append((len(wc_ids), line))

        # Paling sedikit WC lebih dulu; seri -> id terkecil (deterministik).
        capable.sort(key=lambda item: (item[0], item[1].pk))
        return [line for _, line in capable]

    def allocate(
        self, work_order: WorkOrder, routing: ProcessRouting
    ) -> ProductionLine | None:
        """Line paling spesifik yang mampu, atau `None` kalau tidak ada yang mampu."""
        candidates = self.candidates(work_order, routing)
        return candidates[0] if candidates else None
