"""Factory transport master data — satu pintu masuk untuk task master sync.

Pemilihan vendor **hanya** dari ``settings.ERP_ADAPTER`` (tidak ada nilai
hardcode di kode pemanggil), mengikuti pola ``adapters/factory.py``. Kalau vendor
tidak dikenal atau kredensial Odoo belum lengkap, factory **fail-safe**:
mengembalikan :class:`OdooTransport` **tanpa client** (``fetch_*`` → ``[]``)
supaya task master tetap jalan tanpa melempar exception.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from ..client import get_odoo_rpc_client
from .odoo_transport import OdooTransport

logger = logging.getLogger(__name__)


def _build_odoo_transport() -> OdooTransport:
    """``OdooTransport`` dengan ``OdooClient`` dari settings (fail-safe ``None``)."""
    try:
        return OdooTransport(get_odoo_rpc_client())
    except ImproperlyConfigured as exc:
        logger.warning(
            "Kredensial Odoo belum lengkap -> transport master tanpa client (%s).", exc
        )
        return OdooTransport(client=None)


#: Nama vendor (lowercase) -> builder transport master data.
TRANSPORTS: dict[str, Callable[[], OdooTransport]] = {
    "odoo": _build_odoo_transport,
}


def get_transport(name: str | None = None) -> OdooTransport:
    """Instance transport master data sesuai ``settings.ERP_ADAPTER``.

    * ``"odoo"`` → :class:`OdooTransport` (client dibangun dari settings);
    * vendor lain / tidak dikenal → fail-safe :class:`OdooTransport(client=None)`
      sehingga ``fetch_*`` mengembalikan ``[]`` (bukan exception).

    Parameter ``name`` dipakai untuk override eksplisit (mis. dari test).
    """
    requested = (name or getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    builder = TRANSPORTS.get(requested)

    if builder is None:
        logger.warning(
            "ERP_ADAPTER %r tidak punya transport master -> fail-safe tanpa client.",
            requested or None,
        )
        return OdooTransport(client=None)

    logger.info("Transport master aktif: %s", requested)
    return builder()


__all__ = ("TRANSPORTS", "get_transport")
