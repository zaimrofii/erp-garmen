"""WCQueue — queue pekerjaan per work center (Sprint 2.2).

Queue ini **virtual** (query), bukan tabel: bundle yang sedang menunggu/
dikerjakan di sebuah work center adalah bundle dengan
``current_work_center = wc`` dan state belum selesai. Sesuai prinsip blueprint
"aturan & posisi = data", queue tidak perlu tabel sendiri sehingga selalu
konsisten dengan data bundle (tidak ada duplikasi yang bisa basi).

Service ini hanya menyentuh `bundle.current_work_center` (enqueue/dequeue);
perubahan `bundle.state` tetap tanggung jawab pemanggil (Fase 3) supaya
transisi state selalu lewat `core.state_machine`.
"""

from __future__ import annotations

import logging

from django.db.models import QuerySet

from apps_industry.garment.models import Bundle, WorkCenter
from apps_industry.garment.services.exceptions import WCQueueError

logger = logging.getLogger(__name__)


class WCQueue:
    """Queue virtual per work center (stateless)."""

    #: State yang dianggap sudah keluar dari queue.
    EXCLUDED_STATES = ("DONE", "CANCELLED")
    #: Field yang disimpan saat enqueue/dequeue; `version` ikut karena save()
    #: menghitungnya ulang ketika `current_work_center` berubah.
    UPDATE_FIELDS = ("current_work_center", "updated_at", "version")

    def get_queue(self, work_center: WorkCenter) -> QuerySet[Bundle]:
        """Bundle di queue `work_center` (paling lama di-update lebih dulu)."""
        if work_center is None:
            raise WCQueueError("work_center wajib diisi.")
        return (
            Bundle.objects.filter(current_work_center=work_center)
            .exclude(state__in=self.EXCLUDED_STATES)
            .order_by("updated_at", "id")
        )

    def count(self, work_center: WorkCenter) -> int:
        """Jumlah bundle dalam queue `work_center`."""
        return self.get_queue(work_center).count()

    def position(self, bundle: Bundle) -> int | None:
        """Posisi 1-based bundle di queue WC-nya (`None` kalau tidak di queue)."""
        if bundle is None:
            raise WCQueueError("bundle wajib diisi.")
        if bundle.current_work_center_id is None:
            return None

        ids = list(
            self.get_queue(bundle.current_work_center).values_list("pk", flat=True)
        )
        try:
            return ids.index(bundle.pk) + 1
        except ValueError:
            return None  # mis. state bundle sudah DONE/CANCELLED

    def enqueue(self, bundle: Bundle, work_center: WorkCenter) -> Bundle:
        """Masukkan bundle ke queue work center (set `current_work_center`)."""
        if bundle is None or work_center is None:
            raise WCQueueError("bundle dan work_center wajib diisi.")

        bundle.current_work_center = work_center
        bundle.save(update_fields=list(self.UPDATE_FIELDS))
        logger.info("bundle %s masuk queue %s.", bundle.code, work_center.code)
        return bundle

    def dequeue(self, bundle: Bundle) -> Bundle:
        """Keluarkan bundle dari queue (set `current_work_center=None`)."""
        if bundle is None:
            raise WCQueueError("bundle wajib diisi.")

        bundle.current_work_center = None
        bundle.save(update_fields=list(self.UPDATE_FIELDS))
        logger.info("bundle %s keluar dari queue.", bundle.code)
        return bundle
