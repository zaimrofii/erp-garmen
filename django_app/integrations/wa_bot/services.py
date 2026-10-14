"""WhatsApp gateway: kontrak + implementasi mock (Fase 5).

Kenapa mock-first: alur notifikasi (approval supervisor, laporan bottleneck,
HITL) bisa dikembangkan & diuji **tanpa** nomor WA bisnis, tanpa biaya, dan
tanpa risiko mengirim pesan sungguhan ke operator. Implementasi penyedia
sungguhan cukup ditambahkan lalu dipilih lewat ``settings.WA_BACKEND``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = (
    "MockWAGateway",
    "WAGateway",
    "WAMessage",
    "WAResponse",
    "get_wa_gateway",
)


@dataclass
class WAResponse:
    """Hasil pengiriman satu pesan WhatsApp."""

    ok: bool
    message_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Bentuk JSON-safe (untuk log/response API)."""
        return {
            "ok": self.ok,
            "message_id": self.message_id,
            "error": self.error,
            "raw": dict(self.raw),
        }


@dataclass
class WAMessage:
    """Pesan masuk (hasil parsing webhook penyedia WA)."""

    sender: str
    body: str
    timestamp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class WAGateway(ABC):
    """Kontrak gateway WhatsApp (kirim, parse pesan masuk, health check)."""

    #: Nama vendor untuk log/diagnosa (di-override subclass).
    name = "wa"

    @abstractmethod
    def send_message(self, to: str, body: str) -> WAResponse:
        """Kirim pesan teks ke nomor ``to``."""

    @abstractmethod
    def parse_incoming(self, payload: dict) -> WAMessage:
        """Ubah payload webhook menjadi :class:`WAMessage`."""

    @abstractmethod
    def health_check(self) -> bool:
        """True kalau gateway siap dipakai."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name}>"


class MockWAGateway(WAGateway):
    """Gateway palsu: pesan dicatat di memori, tidak ada jaringan sama sekali."""

    name = "mock"

    def __init__(self) -> None:
        #: Riwayat pesan terkirim (untuk diagnosa & assertion test).
        self.sent: list[dict[str, Any]] = []

    def send_message(self, to: str, body: str) -> WAResponse:
        """Catat pesan ke memori + log; selalu sukses kalau input lengkap."""
        recipient = str(to or "").strip()
        text = str(body or "").strip()
        if not recipient or not text:
            error = "Nomor tujuan dan isi pesan wajib diisi."
            logger.warning("[MockWAGateway] kirim ditolak: %s", error)
            return WAResponse(
                ok=False,
                message_id=None,
                raw={"to": recipient, "body": text},
                error=error,
            )

        message_id = f"MOCK-{uuid4()}"
        record = {"to": recipient, "body": text, "message_id": message_id}
        self.sent.append(record)
        logger.info(
            "[MockWAGateway] kirim ke %s: %s (message_id=%s)", recipient, text, message_id
        )
        return WAResponse(ok=True, message_id=message_id, raw=record, error=None)

    def parse_incoming(self, payload: dict) -> WAMessage:
        """Baca payload ``{"from": ..., "text": ...}`` menjadi :class:`WAMessage`."""
        data = dict(payload or {})
        return WAMessage(
            sender=str(data.get("from") or ""),
            body=str(data.get("text") or ""),
            timestamp=self._to_datetime(data.get("timestamp")),
            raw=data,
        )

    def health_check(self) -> bool:
        """Mock selalu siap (tidak ada dependensi eksternal)."""
        return True

    # --------------------------------------------------------------- internal
    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        """Terima ``datetime`` atau string ISO; selain itu -> None (tanpa error)."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("[MockWAGateway] timestamp tidak bisa diparse: %r", value)
        return None


def get_wa_gateway(name: str | None = None) -> WAGateway:
    """Gateway WA sesuai ``settings.WA_BACKEND`` (fallback: mock + log warning).

    Selama belum ada implementasi penyedia sungguhan, semua nilai selain
    ``"mock"`` tetap jatuh ke :class:`MockWAGateway` supaya alur produksi tidak
    mati hanya karena salah konfigurasi.
    """
    requested = (name or getattr(settings, "WA_BACKEND", "") or "").strip().lower()
    if requested in ("", "mock"):
        logger.info("WA gateway aktif: mock.")
        return MockWAGateway()
    logger.warning(
        "WA_BACKEND %r belum diimplementasikan -> fallback MockWAGateway.", requested
    )
    return MockWAGateway()
