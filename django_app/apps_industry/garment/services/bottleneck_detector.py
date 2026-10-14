"""BottleneckDetector — deteksi work center yang jadi bottleneck (Sprint 2.3).

Read-only, memakai queue **virtual** (`WCQueue.get_queue`) sebagai sumber data:

  * ``queue_depth``      — jumlah bundle menunggu di WC;
  * ``avg_wait_minutes`` — rata-rata umur antrian (``now - bundle.updated_at``)
    sebagai proksi waktu tunggu, karena queue virtual tidak punya timestamp
    masuk sendiri;
  * ``is_bottleneck``    — True kalau ``queue_depth > queue_depth_threshold``
    **atau** ``avg_wait_minutes > avg_wait_threshold_minutes``.

Threshold bisa di-override lewat konstruktor (default 10 bundle / 60 menit).
Service tidak menulis apa pun dan tidak mengirim notifikasi (sinkron murni).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps_industry.garment.models import WorkCenter
from apps_industry.garment.services.exceptions import BottleneckDetectorError
from apps_industry.garment.services.wc_queue import WCQueue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BottleneckReport:
    """Hasil analisis satu work center."""

    work_center: WorkCenter
    queue_depth: int
    avg_wait_minutes: float
    is_bottleneck: bool
    reason: str


class BottleneckDetector:
    """Deteksi bottleneck per work center (stateless, read-only)."""

    def __init__(
        self,
        queue_depth_threshold: int = 10,
        avg_wait_threshold_minutes: float = 60,
    ):
        self.queue_depth_threshold = queue_depth_threshold
        self.avg_wait_threshold_minutes = avg_wait_threshold_minutes
        self._queue = WCQueue()

    def detect(self, work_center: WorkCenter) -> BottleneckReport:
        """Analisis satu work center."""
        if work_center is None:
            raise BottleneckDetectorError("work_center wajib diisi.")

        queue = list(self._queue.get_queue(work_center))
        depth = len(queue)
        avg_wait = self._avg_wait_minutes(queue)

        reasons: list[str] = []
        if depth > self.queue_depth_threshold:
            reasons.append(f"queue {depth} > ambang {self.queue_depth_threshold}")
        if avg_wait > self.avg_wait_threshold_minutes:
            reasons.append(
                f"rata-rata tunggu {avg_wait:.1f} menit > "
                f"ambang {self.avg_wait_threshold_minutes}"
            )

        return BottleneckReport(
            work_center=work_center,
            queue_depth=depth,
            avg_wait_minutes=round(avg_wait, 2),
            is_bottleneck=bool(reasons),
            reason="; ".join(reasons) if reasons else "normal",
        )

    def detect_all(self) -> list[BottleneckReport]:
        """Analisis semua work center aktif (urut kode WC)."""
        return [
            self.detect(work_center)
            for work_center in WorkCenter.objects.filter(is_active=True).order_by("code")
        ]

    def top_n(self, n: int = 5) -> list[BottleneckReport]:
        """`n` bottleneck terparah (queue_depth desc, tie-break avg_wait desc)."""
        try:
            n_int = int(n)
        except (TypeError, ValueError) as exc:
            raise BottleneckDetectorError("n harus bilangan bulat > 0.") from exc
        if n_int <= 0:
            raise BottleneckDetectorError("n harus bilangan bulat > 0.")

        reports = [report for report in self.detect_all() if report.is_bottleneck]
        reports.sort(
            key=lambda report: (
                -report.queue_depth,
                -report.avg_wait_minutes,
                report.work_center.code,
            )
        )
        return reports[:n_int]

    @staticmethod
    def _avg_wait_minutes(bundles) -> float:
        """Rata-rata `now - updated_at` (menit); 0.0 kalau queue kosong."""
        if not bundles:
            return 0.0
        now = timezone.now()
        waits = [(now - bundle.updated_at).total_seconds() / 60 for bundle in bundles]
        return sum(waits) / len(waits)
