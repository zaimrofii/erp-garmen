"""OverlapRelease — pelepasan step berikutnya dari DAG routing (Sprint 2.2).

Alur produksi garmen = **DAG + rework loop**. Service ini hanya **membaca** DAG
(`RoutingStep.allowed_next_steps`) dan mengembalikan step berikutnya; ia TIDAK
mengubah state bundle. Pemanggil yang men-set `bundle.current_work_center` +
`state` (dan menulis `BundleEvent`) supaya perubahan state terpusat di satu
tempat dan mudah diaudit.

Routing aktif = ``ProcessRouting.is_active=True``. Kalau ada lebih dari satu
routing aktif, dipakai yang **pertama berdasarkan id** (deterministik); cara
yang disarankan adalah meng-inject routing eksplisit dari
`TagRouter.resolve()` lewat konstruktor.
"""

from __future__ import annotations

import logging

from apps_industry.garment.models import Bundle, ProcessRouting, RoutingStep
from apps_industry.garment.services.exceptions import OverlapReleaseError

logger = logging.getLogger(__name__)


class OverlapRelease:
    """Pembaca DAG routing: step saat ini, step lanjutan, kandidat rilis."""

    def __init__(self, routing: ProcessRouting | None = None):
        """`routing` opsional; kalau None, service memakai routing aktif pertama."""
        self._routing = routing

    @property
    def routing(self) -> ProcessRouting | None:
        """Routing yang dipakai (inject, atau routing aktif pertama by id)."""
        if self._routing is not None:
            return self._routing
        return ProcessRouting.objects.filter(is_active=True).order_by("id").first()

    def get_current_step(self, bundle: Bundle) -> RoutingStep | None:
        """Step routing yang cocok dengan `bundle.current_work_center`.

        `None` kalau bundle belum punya work center, atau routing aktif tidak
        punya step untuk work center tersebut.
        """
        if bundle is None:
            raise OverlapReleaseError("bundle wajib diisi.")

        routing = self.routing
        if routing is None or bundle.current_work_center_id is None:
            return None
        return (
            routing.steps.filter(work_center_id=bundle.current_work_center_id)
            .order_by("order", "id")
            .first()
        )

    def get_next_steps(self, bundle: Bundle) -> list[RoutingStep]:
        """Kandidat step lanjutan dari `current_step.allowed_next_steps`."""
        current = self.get_current_step(bundle)
        if current is None:
            return []
        return list(current.allowed_next_steps.order_by("order", "id"))

    def release(self, bundle: Bundle) -> RoutingStep | None:
        """Step berikutnya yang **eligible**, atau `None`.

        `None` diberikan kalau: bundle belum punya current step, step saat ini
        terminal (`is_terminal=True`), atau tidak ada step lanjutan yang eligible.
        """
        current = self.get_current_step(bundle)
        if current is None or current.is_terminal:
            return None

        for candidate in self.get_next_steps(bundle):
            if self._is_eligible(candidate):
                return candidate

        logger.info(
            "tidak ada step lanjutan eligible dari step '%s' (bundle %s).",
            current.code,
            getattr(bundle, "code", bundle.pk),
        )
        return None

    @staticmethod
    def _is_eligible(step: RoutingStep) -> bool:
        """Step eligible kalau work center-nya belum ditentukan atau masih aktif."""
        work_center = step.work_center
        if work_center is None:
            return True
        return bool(work_center.is_active)
