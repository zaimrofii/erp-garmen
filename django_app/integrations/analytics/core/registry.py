"""Registry metrik analytics (in-memory) + autodiscover plugin.

Desain mengikuti pola `core/event_bus/registry.py` (registrasi saat app ready,
salinan aman untuk pembaca, fungsi `_reset_for_tests`). Bedanya: metrik
di-autodiscover dari `plugins/<domain>/plugin.py` supaya domain baru cukup
menambah folder plugin (tanpa mengubah modul inti).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from collections.abc import Iterable

from .metric import MetricDefinition

logger = logging.getLogger(__name__)

#: metric_id -> definisi (urutan pendaftaran dipertahankan oleh dict).
_REGISTRY: dict[str, MetricDefinition] = {}

#: Guard idempotensi autodiscover (app `ready()` bisa terpanggil beberapa kali
#: di environment test).
_DISCOVERED = False


def _validate_metric(metric: MetricDefinition) -> None:
    """Validasi bentuk metrik sebelum masuk registry.

    Aturan: `metric_id` harus ``<domain>.<name>`` dan domain prefix HARUS sama
    dengan field `domain` (mencegah plugin salah menaruh metrik).
    """
    metric_id = getattr(metric, "metric_id", "")
    if not isinstance(metric_id, str) or metric_id.count(".") != 1:
        raise ValueError(
            f"metric_id harus berformat <domain>.<name>: {metric_id!r}"
        )

    domain, _, name = metric_id.partition(".")
    if not domain or not name:
        raise ValueError(
            f"metric_id harus berformat <domain>.<name>: {metric_id!r}"
        )
    if domain != metric.domain:
        raise ValueError(
            f"domain pada metric_id ({domain!r}) != field domain ({metric.domain!r})"
        )
    if not metric.granularities:
        raise ValueError(f"metrik {metric_id} harus punya minimal 1 granularity")
    if not metric.dimensions:
        raise ValueError(f"metrik {metric_id} harus punya minimal 1 dimension")
    if not callable(metric.compute):
        raise ValueError(f"metrik {metric_id}: compute harus callable")


def register_metric(metric: MetricDefinition) -> MetricDefinition:
    """Daftarkan metrik. Duplikat `metric_id` → ValueError.

    Mengembalikan `metric` supaya aman dipakai sebagai nilai balik plugin.
    """
    _validate_metric(metric)
    if metric.metric_id in _REGISTRY:
        raise ValueError(f"metric_id duplikat: {metric.metric_id}")

    _REGISTRY[metric.metric_id] = metric
    logger.debug("analytics: metrik %s terdaftar.", metric.metric_id)
    return metric


def is_registered(metric_id: str) -> bool:
    """True kalau `metric_id` sudah ada di registry (tanpa memicu autodiscover)."""
    return metric_id in _REGISTRY


def discover_metrics() -> int:
    """Autodiscover semua plugin ``plugins/<domain>/plugin.py``. Idempoten.

    Mengembalikan jumlah metrik terdaftar. Plugin yang belum punya `plugin.py`
    dilewati; **ImportError nyata di dalam plugin TIDAK ditelan** supaya bug
    plugin terlihat saat startup (berbeda dari prompt awal yang menelan semua
    ImportError — lihat laporan B.1).
    """
    global _DISCOVERED
    if _DISCOVERED:
        return len(_REGISTRY)

    from integrations.analytics import plugins

    for _finder, modname, ispkg in pkgutil.iter_modules(plugins.__path__):
        if not ispkg:
            continue

        module_name = f"{plugins.__name__}.{modname}.plugin"
        if importlib.util.find_spec(module_name) is None:
            logger.debug(
                "analytics: plugin %s belum punya plugin.py — dilewati.", modname
            )
            continue

        module = importlib.import_module(module_name)
        register = getattr(module, "register", None)
        if callable(register):
            register()

    _DISCOVERED = True
    return len(_REGISTRY)


def get_metric(metric_id: str) -> MetricDefinition:
    """Ambil definisi metrik. Raise ``KeyError`` bila tidak terdaftar."""
    if not _DISCOVERED:
        discover_metrics()

    try:
        return _REGISTRY[metric_id]
    except KeyError:
        raise KeyError(f"metrik tidak terdaftar: {metric_id}") from None


def list_metrics(domain: str | None = None) -> list[MetricDefinition]:
    """Daftar metrik (opsional difilter domain), urut pendaftaran."""
    if not _DISCOVERED:
        discover_metrics()

    metrics: Iterable[MetricDefinition] = _REGISTRY.values()
    if domain:
        return [metric for metric in metrics if metric.domain == domain]
    return list(metrics)


def _reset_for_tests() -> None:
    """HANYA untuk test: kosongkan registry + flag autodiscover."""
    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False


__all__ = (
    "discover_metrics",
    "get_metric",
    "list_metrics",
    "register_metric",
)
