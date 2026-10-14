"""Adapter SAP (stub) — roadmap multi-vendor ERP.

Sengaja belum diimplementasikan: semua method melempar ``NotImplementedError``
supaya salah konfigurasi (``ERP_ADAPTER=sap``) langsung terlihat.
"""

from __future__ import annotations

from .base import ERPAdapter, ERPResponse

MESSAGE = "Adapter SAP belum diimplementasikan (roadmap multi-vendor ERP)."


class SapAdapter(ERPAdapter):
    """Stub adapter SAP (S/4HANA / Business One)."""

    name = "sap"

    def push_wip_issue(self, payload: dict) -> ERPResponse:
        raise NotImplementedError(MESSAGE)

    def push_fg_receipt(self, payload: dict) -> ERPResponse:
        raise NotImplementedError(MESSAGE)

    def health_check(self) -> bool:
        raise NotImplementedError(MESSAGE)
