"""Implementasi service toggle analytics (TOGGLE-CONTRACT §2–§7)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit.models import AuditLog
from core.audit.services import AuditLogger

from ..models import AnalyticsConfig

logger = logging.getLogger(__name__)

#: Kode alasan OFF (TOGGLE-CONTRACT §2.2).
REASON_NOT_YET_ENABLED = "not_yet_enabled"
REASON_DISABLED = "analytics_disabled"

#: Bundle yang dianggap "selesai" (tidak aktif) — konsisten dengan ERP sync.
BUNDLE_DONE_STATES = ("DONE", "CANCELLED")

#: Kode soft blocker (format code-only, count ada di `counts`).
SOFT_NO_ACTIVE_BUNDLES = "no_active_bundles"

#: Prefix cache analytics (diinvalidasi setiap config berubah).
CACHE_PREFIX = "analytics:"
CACHE_VERSION_KEY = "analytics:cache_version"


class ReadinessFailed(Exception):
    """Enable ditolak karena hard blocker readiness."""

    def __init__(self, blockers: list[str], checked_at: str | None = None):
        super().__init__("Kesiapan data belum terpenuhi")
        self.blockers = list(blockers)
        self.checked_at = checked_at or timezone.now().isoformat()


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def cache_version() -> int:
    """Versi cache analytics (bagian dari cache key di B.7)."""
    value = cache.get(CACHE_VERSION_KEY)
    return int(value) if value is not None else 0


def invalidate_cache() -> None:
    """Invalidasi cache analytics (dipakai listener & aksi toggle)."""
    _invalidate_cache()


def _invalidate_cache() -> None:
    """Invalidasi cache analytics (prefix) — aman untuk backend tanpa pattern."""
    delete_pattern = getattr(cache, "delete_pattern", None)
    if callable(delete_pattern):
        try:
            delete_pattern(f"{CACHE_PREFIX}*")
            return
        except Exception:  # noqa: BLE001 - backend cache tidak boleh memblokir
            logger.warning("analytics: delete_pattern gagal, pakai versi cache.")

    try:
        cache.incr(CACHE_VERSION_KEY)
    except ValueError:
        cache.set(CACHE_VERSION_KEY, 1, None)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def get_config() -> AnalyticsConfig:
    """Ambil config singleton (dibuat default OFF bila belum ada) — tidak pernah None."""
    config, _created = AnalyticsConfig.objects.get_or_create(pk=1)
    return config


def config_payload(config: AnalyticsConfig) -> dict[str, Any]:
    """Bentuk response TOGGLE-CONTRACT §3.1."""
    from ..plugins.garment.models import MetricSnapshot

    return {
        "enabled": bool(config.enabled),
        "enabled_domains": list(config.enabled_domains or []),
        "enabled_metrics": list(config.enabled_metrics or []),
        "data_readiness_acknowledged_at": _iso(config.data_readiness_acknowledged_at),
        "enabled_by": config.enabled_by_id,
        "enabled_at": _iso(config.enabled_at),
        "disabled_reason": config.disabled_reason,
        "historical_data_available": MetricSnapshot.objects.exists(),
        "updated_at": _iso(config.updated_at),
    }


def analytics_enabled() -> bool:
    """Shortcut master switch."""
    return bool(get_config().enabled)


def is_metric_enabled(metric_id: str) -> bool:
    """Evaluasi 5 baris tabel TOGGLE-CONTRACT §5."""
    config = get_config()

    if not config.enabled:
        return False

    metrics = list(config.enabled_metrics or [])
    if metrics:
        # enabled_metrics MENANG atas enabled_domains.
        return metric_id in metrics

    domains = list(config.enabled_domains or [])
    if domains:
        return metric_id.split(".")[0] in domains

    return True  # permissive default


def _iso(value) -> str | None:
    if value is None:
        return None
    return timezone.localtime(value).isoformat()


def _audit(user, action: str, metadata: dict, request=None, result=AuditLog.Result.OK):
    """Tulis AuditLog; kegagalan audit tidak boleh menggagalkan aksi bisnis."""
    try:
        AuditLogger().log(
            user=user,
            action=action,
            resource="analytics_config",
            resource_id=1,
            request=request,
            metadata=metadata,
            result=result,
        )
    except Exception:  # noqa: BLE001
        logger.exception("analytics: gagal menulis AuditLog %s.", action)


def _normalize_list(value: Any, field: str) -> list[str]:
    """Validasi list[str] (nilai non-list / item non-string → ValidationError)."""
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{field} harus list string")
    return [item for item in value if item]


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
HARD_BLOCKERS = (
    "products_without_odoo_id_in_active_bundles",
    "bundles_without_events_older_than_24h",
    "scrap_without_accumulator_older_than_24h",
    "sync_records_failed_recent_7d",
)

_SOFT_MESSAGES = {
    SOFT_NO_ACTIVE_BUNDLES: (
        "Tidak ada bundle aktif; analytics akan kosong sampai ada produksi."
    ),
}


def _collect_counts() -> dict[str, int]:
    """Hitung semua angka readiness (DB MES saja; tanpa Odoo live)."""
    from apps_industry.garment.models import Bundle, BundleEvent, OrderLine
    from integrations.erp_sync.models import SyncRecord, SyncStatus
    from master.models import Product

    now = timezone.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    active_bundles = Bundle.objects.exclude(state__in=BUNDLE_DONE_STATES)
    active_count = active_bundles.count()

    product_ids = OrderLine.objects.filter(
        work_orders__bundles__in=active_bundles
    ).values_list("product_id", flat=True)

    return {
        "products_without_odoo_id_total": Product.objects.filter(
            odoo_id__isnull=True
        ).count(),
        "products_without_odoo_id_in_active_bundles": Product.objects.filter(
            pk__in=product_ids, odoo_id__isnull=True
        )
        .distinct()
        .count(),
        "active_bundles": active_count,
        "bundles_without_events_older_than_24h": active_bundles.filter(
            created_at__lt=cutoff_24h, events__isnull=True
        )
        .distinct()
        .count(),
        "scrap_without_accumulator_older_than_24h": BundleEvent.objects.filter(
            event_type__in=("SCRAP", "REWORK"),
            ts__lt=cutoff_24h,
            bundle__scraps__isnull=True,
        )
        .distinct()
        .count(),
        "sync_records_failed_recent_7d": SyncRecord.objects.filter(
            status=SyncStatus.FAILED, updated_at__gte=cutoff_7d
        ).count(),
    }


def readiness_report() -> dict[str, Any]:
    """Shape TOGGLE-CONTRACT §3.5. `ready ⇔ blockers == []` (soft tidak memblokir)."""
    counts = _collect_counts()

    blockers = [f"{key}:{counts[key]}" for key in HARD_BLOCKERS if counts[key] > 0]
    soft_blockers = [SOFT_NO_ACTIVE_BUNDLES] if counts["active_bundles"] == 0 else []

    return {
        "ready": blockers == [],
        "blockers": blockers,
        "soft_blockers": soft_blockers,
        "checked_at": timezone.now().isoformat(),
        "thresholds": {key: counts[key] for key in HARD_BLOCKERS},
        "counts": counts,
    }


# --------------------------------------------------------------------------- #
# Aksi toggle
# --------------------------------------------------------------------------- #
def enable(
    by_user,
    enabled_domains: Any = None,
    enabled_metrics: Any = None,
) -> dict[str, Any]:
    """Enable analytics — readiness dicek ULANG setiap kali (bukan izin permanen)."""
    domains = _normalize_list(enabled_domains, "enabled_domains")
    metrics = _normalize_list(enabled_metrics, "enabled_metrics")
    report: dict[str, Any] | None = None

    # Pastikan baris singleton ada DI LUAR transaksi: kalau enable diblokir,
    # rollback tidak boleh menghapus konfigurasi default OFF.
    get_config()

    try:
        with transaction.atomic():
            config = AnalyticsConfig.objects.select_for_update().get(pk=1)
            report = readiness_report()

            if report["blockers"]:
                raise ReadinessFailed(report["blockers"], report["checked_at"])

            now = timezone.now()
            config.enabled = True
            config.enabled_by = by_user if getattr(by_user, "pk", None) else None
            config.enabled_at = now
            config.data_readiness_acknowledged_at = now
            config.disabled_reason = ""
            config.enabled_domains = domains
            config.enabled_metrics = metrics
            config.save()

            _audit(
                by_user,
                "analytics.enable_success",
                {"enabled_domains": domains, "enabled_metrics": metrics},
            )
    except ReadinessFailed as exc:
        _audit(
            by_user,
            "analytics.enable_blocked",
            {"blockers": exc.blockers, "checked_at": exc.checked_at},
            result=AuditLog.Result.DENIED,
        )
        raise

    _invalidate_cache()
    assert report is not None
    warnings = [
        {"code": code, "message": _SOFT_MESSAGES.get(code, code)}
        for code in report["soft_blockers"]
    ]
    return {**config_payload(config), "readiness": report, "warnings": warnings}


def disable(reason: str, user=None, request=None) -> dict[str, Any]:
    """Disable analytics — alasan WAJIB; snapshot TIDAK dihapus."""
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValidationError("Alasan disable wajib diisi")

    with transaction.atomic():
        get_config()
        config = AnalyticsConfig.objects.select_for_update().get(pk=1)
        config.enabled = False
        config.disabled_reason = REASON_DISABLED
        config.save()
        _audit(
            user,
            "analytics.disable",
            {"reason": cleaned},
            request=request,
        )

    _invalidate_cache()
    return config_payload(config)


def update_filters(
    enabled_domains: Any = None,
    enabled_metrics: Any = None,
    user=None,
    request=None,
) -> dict[str, Any]:
    """Ubah filter domain/metrik (PUT) — BUKAN enable/disable."""
    domains = _normalize_list(enabled_domains, "enabled_domains")
    metrics = _normalize_list(enabled_metrics, "enabled_metrics")

    with transaction.atomic():
        get_config()
        config = AnalyticsConfig.objects.select_for_update().get(pk=1)
        before = {
            "enabled_domains": list(config.enabled_domains or []),
            "enabled_metrics": list(config.enabled_metrics or []),
        }
        config.enabled_domains = domains
        config.enabled_metrics = metrics
        config.save()
        _audit(
            user,
            "analytics.config_update",
            {
                "before": before,
                "after": {"enabled_domains": domains, "enabled_metrics": metrics},
            },
            request=request,
        )

    _invalidate_cache()
    return config_payload(config)


