"""Listener event bus analytics (B.3) — event-driven, bukan polling.

Kontrak: docs/analytics/CONTRACT.md §9.
Aturan: idempoten, TIDAK menulis tabel bisnis, kegagalan ditelan + log ERROR
(tidak boleh menggagalkan aksi operator).
"""

from __future__ import annotations

import logging

from core.event_bus.registry import register_listener
from core.event_bus.signals import BUNDLE_STATE_CHANGED, SCRAP_RECORDED

logger = logging.getLogger(__name__)

#: Belum ada konstanta di `core.event_bus.signals`; nama event mengikuti kontrak.
SYNC_RECORD_CHANGED = "SYNC_RECORD_CHANGED"

#: Event internal analytics (dipublikasikan service toggle).
ANALYTICS_CONFIG_CHANGED = "analytics.config_changed"

_EVENTS = (
    BUNDLE_STATE_CHANGED,
    SCRAP_RECORDED,
    SYNC_RECORD_CHANGED,
    ANALYTICS_CONFIG_CHANGED,
)

_REGISTERED = False


def handle_bundle_state_changed(*, event_name=None, payload=None) -> None:
    """Bundle berubah → cache metrik bundle tidak valid lagi."""
    del event_name  # kontrak dispatcher; tidak dipakai
    try:
        from ..services.analytics_config_services import invalidate_cache

        invalidate_cache()
        try:
            from integrations.ai_agent.memory import semantic_cache

            semantic_cache.invalidate(trigger="bundle_event")
        except Exception:  # noqa: BLE001 - cache AI opsional, jangan ganggu operator
            logger.exception("analytics: gagal invalidasi semantic cache bundle.")
        logger.debug("analytics: cache diinvalidasi (BUNDLE_STATE_CHANGED %s).", payload)
    except Exception:  # noqa: BLE001 - listener tidak boleh menggagalkan operator
        logger.exception("analytics: gagal menangani BUNDLE_STATE_CHANGED.")


def handle_scrap_recorded(*, event_name=None, payload=None) -> None:
    """Scrap tercatat → invalidasi cache + (B.4) stream check."""
    del event_name
    try:
        from ..services.analytics_config_services import invalidate_cache

        invalidate_cache()
        try:
            from integrations.ai_agent.memory import semantic_cache

            semantic_cache.invalidate(trigger="scrap_event")
        except Exception:  # noqa: BLE001 - cache AI opsional, jangan ganggu operator
            logger.exception("analytics: gagal invalidasi semantic cache scrap.")
        logger.debug("analytics: cache diinvalidasi (SCRAP_RECORDED %s).", payload)
    except Exception:  # noqa: BLE001
        logger.exception("analytics: gagal menangani SCRAP_RECORDED.")


def handle_sync_record_changed(*, event_name=None, payload=None) -> None:
    """SyncRecord berubah → readiness/cache analytics mungkin berubah."""
    del event_name
    try:
        from ..services.analytics_config_services import invalidate_cache

        invalidate_cache()
        logger.debug("analytics: cache diinvalidasi (SYNC_RECORD_CHANGED %s).", payload)
    except Exception:  # noqa: BLE001
        logger.exception("analytics: gagal menangani SYNC_RECORD_CHANGED.")


def handle_config_changed(*, event_name=None, payload=None) -> None:
    """Konfigurasi toggle berubah → cache filter runtime dibuang."""
    del event_name
    try:
        from ..services.analytics_config_services import invalidate_cache

        invalidate_cache()
        logger.debug("analytics: cache diinvalidasi (config_changed %s).", payload)
    except Exception:  # noqa: BLE001
        logger.exception("analytics: gagal menangani analytics.config_changed.")


_LISTENERS = (
    (BUNDLE_STATE_CHANGED, handle_bundle_state_changed),
    (SCRAP_RECORDED, handle_scrap_recorded),
    (SYNC_RECORD_CHANGED, handle_sync_record_changed),
    (ANALYTICS_CONFIG_CHANGED, handle_config_changed),
)


def register_all() -> None:
    """Daftarkan 4 listener (idempoten; hormati flag `event_bus_listener`)."""
    global _REGISTERED

    from ..config import ANALYTICS_CONFIG

    if not ANALYTICS_CONFIG.get("event_bus_listener", True):
        logger.info("analytics: listener event bus DIMATIKAN oleh config.")
        return

    if _REGISTERED:
        return

    for event_name, listener in _LISTENERS:
        register_listener(event_name, listener)

    _REGISTERED = True
    logger.info("analytics: %d listener event bus terdaftar.", len(_LISTENERS))


def _reset_for_tests() -> None:
    """HANYA test: lupakan flag registrasi (listener di registry dikelola test)."""
    global _REGISTERED
    _REGISTERED = False


__all__ = (
    "ANALYTICS_CONFIG_CHANGED",
    "SYNC_RECORD_CHANGED",
    "handle_bundle_state_changed",
    "handle_config_changed",
    "handle_scrap_recorded",
    "handle_sync_record_changed",
    "register_all",
)

