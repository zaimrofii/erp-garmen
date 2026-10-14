"""Paket `integrations.erp_sync.adapters` — abstraksi akses ERP supaya Django
tidak terikat ke implementasi vendor mana pun.

Dua kontrak (lihat ``base.py``):

* ``ERPAdapter`` — kontrak bisnis **two-stage sync** (``push_wip_issue``,
  ``push_fg_receipt``, ``health_check``);
* ``ERPTransport`` — transport tingkat rendah (login/search_read/create/write/
  call) untuk master data & task diagnosa.

Isi paket:

  * ``base``     : ``ERPResponse``, ``ERPAdapterError``, ``ERPAdapter``, ``ERPTransport``
  * ``null``     : ``NullAdapter``   (no-op, erp_id = ``NULL-<uuid4>``)
  * ``odoo``     : ``OdooAdapter``   (skeleton Sprint 4.2) + ``OdooJSONRPCAdapter`` (transport JSON-RPC)
  * ``accurate`` : ``AccurateAdapter`` (stub)
  * ``sap``      : ``SapAdapter``      (stub)
  * ``factory``  : ``get_adapter()`` — pilih adapter dari ``settings.ERP_ADAPTER``
"""

from .base import (
    STAGE_FG,
    STAGE_WIP,
    ERPAdapter,
    ERPAdapterError,
    ERPResponse,
    ERPTransport,
)

__all__ = (
    "STAGE_FG",
    "STAGE_WIP",
    "ERPAdapter",
    "ERPAdapterError",
    "ERPResponse",
    "ERPTransport",
)
