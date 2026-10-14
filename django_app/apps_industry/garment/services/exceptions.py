"""Exception service layer garmen (Sprint 2.2).

Semua error service diturunkan dari `ServiceError` supaya pemanggil (API Fase 3,
task Celery, atau test) cukup menangkap satu tipe dasar. `ServiceError` sendiri
turunan `django.core.exceptions.ValidationError` — konsisten dengan engine core
(`StateMachineEngineError`, `CycleHandlerError`) dan otomatis ramah DRF
(400 alih-alih 500) saat endpoint garmen dibuat di Fase 3.

Setiap service punya turunan sendiri supaya pesan error bisa dibedakan dan
pemanggil bisa menangkap yang spesifik bila perlu.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError


class ServiceError(ValidationError):
    """Base semua error service garmen."""


class BundleEngineError(ServiceError):
    """Error pembentukan bundle (bundle_size / matriks ukuran tidak valid)."""


class OverlapReleaseError(ServiceError):
    """Error pembacaan DAG routing (input/routing tidak konsisten)."""


class ReworkLoopError(ServiceError):
    """Error siklus rework QC (mis. belum ada instance siklus aktif)."""


class TagRouterError(ServiceError):
    """Error resolusi tag (routing/kupon tidak bisa ditentukan dari rule)."""


class CapabilityAllocatorError(ServiceError):
    """Error alokasi line produksi (input tidak lengkap)."""


class WCQueueError(ServiceError):
    """Error operasi queue work center (mis. work center tidak diisi)."""


class TwoStageAggregatorError(ServiceError):
    """Error penyusunan payload stok dua tahap (tahap WIP/FG tidak sesuai)."""


class ScrapAccumulatorError(ServiceError):
    """Error akumulasi scrap (qty/bundle/work center tidak valid)."""


class PrioritySchedulerError(ServiceError):
    """Error perhitungan prioritas (input tidak lengkap / nilai SET_PRIORITY salah)."""


class BottleneckDetectorError(ServiceError):
    """Error deteksi bottleneck (work center / n tidak valid)."""
