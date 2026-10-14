"""Factory adapter ERP bisnis — satu pintu masuk untuk task & endpoint sync.

Pemilihan vendor **hanya** dari ``settings.ERP_ADAPTER`` (tidak ada nilai
hardcode di kode pemanggil). Kalau nilainya tidak dikenal (salah tulis, vendor
belum tersedia), factory **fail-safe** ke :class:`NullAdapter` supaya alur
produksi tetap jalan dan masalahnya terlihat di log.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .accurate import AccurateAdapter
from .base import ERPAdapter
from .null import NullAdapter
from .odoo import OdooAdapter
from .sap import SapAdapter

logger = logging.getLogger(__name__)

#: Adapter yang dipakai kalau `ERP_ADAPTER` tidak dikenal/kosong.
DEFAULT_ADAPTER = "null"

#: Nama vendor (lowercase) -> kelas adapter two-stage sync.
ADAPTERS: dict[str, type[ERPAdapter]] = {
    "null": NullAdapter,
    "odoo": OdooAdapter,
    "accurate": AccurateAdapter,
    "sap": SapAdapter,
}


def get_adapter(name: str | None = None) -> ERPAdapter:
    """Instance adapter ERP sesuai ``settings.ERP_ADAPTER``.

    * ``"odoo"``     -> :class:`OdooAdapter` (skeleton; client di-inject Sprint 4.2)
    * ``"null"``     -> :class:`NullAdapter` (development/testing)
    * ``"accurate"`` -> :class:`AccurateAdapter` (stub, raise)
    * ``"sap"``      -> :class:`SapAdapter` (stub, raise)
    * tidak dikenal  -> :class:`NullAdapter` (fail-safe + log WARNING)

    Parameter ``name`` dipakai untuk override eksplisit (mis. dari test atau
    tombol "Sync sekarang" di UI admin).
    """
    requested = (name or getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    adapter_cls = ADAPTERS.get(requested)

    if adapter_cls is None:
        logger.warning(
            "ERP_ADAPTER %r tidak dikenal -> fallback ke %s (fail-safe).",
            requested or None,
            NullAdapter.name,
        )
        return NullAdapter()

    logger.info("ERP adapter aktif: %s", adapter_cls.name)
    return adapter_cls()
