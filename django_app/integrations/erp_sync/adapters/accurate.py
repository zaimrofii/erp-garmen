"""Adapter Accurate (stub) — roadmap multi-vendor ERP.

Sengaja belum diimplementasikan: semua method melempar ``NotImplementedError``
supaya salah konfigurasi (``ERP_ADAPTER=accurate`` tanpa implementasi) langsung
terlihat, bukan diam-diam mengirim data ke mana-mana.
"""

from __future__ import annotations

from .base import ERPAdapter, ERPResponse

MESSAGE = "Adapter Accurate belum diimplementasikan (roadmap multi-vendor ERP)."


class AccurateAdapter(ERPAdapter):
    """Stub adapter Accurate Online."""

    name = "accurate"

    def push_wip_issue(self, payload: dict) -> ERPResponse:
        raise NotImplementedError(MESSAGE)

    def push_fg_receipt(self, payload: dict) -> ERPResponse:
        raise NotImplementedError(MESSAGE)

    def health_check(self) -> bool:
        raise NotImplementedError(MESSAGE)
