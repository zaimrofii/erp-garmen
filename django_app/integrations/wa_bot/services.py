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
    "FonnteGateway",
    "MockWAGateway",
    "WAGateway",
    "WAMessage",
    "WAResponse",
    "get_wa_gateway",
    "send_hitl_notification",
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
        body = data.get("text")
        if body is None:
            body = data.get("message")
        return WAMessage(
            sender=str(data.get("from") or ""),
            body=str(body or ""),
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


class FonnteGateway(WAGateway):
    """Gateway Fonnte (https://fonnte.com) — kirim via HTTP API."""

    name = "fonnte"

    def __init__(self, api_key: str, api_url: str | None = None) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_url = (api_url or "https://api.fonnte.com/send").strip()

    def send_message(self, to: str, body: str) -> WAResponse:
        recipient = str(to or "").strip()
        text = str(body or "").strip()
        if not recipient or not text:
            return WAResponse(ok=False, error="Nomor tujuan dan isi pesan wajib diisi.")
        if not self.api_key:
            return WAResponse(ok=False, error="WA_API_KEY kosong.")

        try:
            import httpx

            response = httpx.post(
                self.api_url,
                headers={"Authorization": self.api_key},
                data={"target": recipient, "message": text},
                timeout=10.0,
            )
            payload = response.json() if response.content else {}
        except Exception as exc:  # noqa: BLE001 - jaringan tidak boleh crash
            logger.warning("[FonnteGateway] kirim gagal: %s", exc)
            return WAResponse(ok=False, error=str(exc))

        ok = bool(payload.get("status")) if isinstance(payload, dict) else False
        message_id = None
        if isinstance(payload, dict):
            ids = payload.get("id")
            if isinstance(ids, list) and ids:
                message_id = str(ids[0])
            elif ids is not None:
                message_id = str(ids)

        error = None
        if not ok:
            error = (
                str(payload.get("reason") or "fonnte_failed")
                if isinstance(payload, dict)
                else "fonnte_failed"
            )

        return WAResponse(
            ok=ok,
            message_id=message_id,
            raw=payload if isinstance(payload, dict) else {"raw": str(payload)},
            error=error,
        )

    def parse_incoming(self, payload: dict) -> WAMessage:
        """Payload Fonnte: ``{sender, message, ...}``."""
        data = dict(payload or {})
        return WAMessage(
            sender=str(data.get("sender") or data.get("from") or ""),
            body=str(data.get("message") or data.get("text") or ""),
            timestamp=MockWAGateway._to_datetime(data.get("timestamp")),
            raw=data,
        )

    def health_check(self) -> bool:
        return bool(self.api_key)


def get_wa_gateway(name: str | None = None) -> WAGateway:
    """Gateway WA sesuai ``settings.WA_BACKEND`` (fallback: mock + log warning).

    ``fonnte`` dipakai hanya bila ``WA_API_KEY`` terisi; konfigurasi tidak
    lengkap selalu jatuh ke :class:`MockWAGateway` supaya alur produksi tidak
    mati hanya karena salah konfigurasi.
    """
    requested = (name or getattr(settings, "WA_BACKEND", "") or "").strip().lower()

    if requested == "fonnte":
        api_key = str(getattr(settings, "WA_API_KEY", "") or "").strip()
        if api_key:
            return FonnteGateway(api_key, getattr(settings, "WA_API_URL", None))
        logger.warning("WA_BACKEND 'fonnte' tanpa WA_API_KEY -> fallback MockWAGateway.")
        return MockWAGateway()

    if requested in ("", "mock"):
        logger.info("WA gateway aktif: mock.")
        return MockWAGateway()

    logger.warning(
        "WA_BACKEND %r belum diimplementasikan -> fallback MockWAGateway.", requested
    )
    return MockWAGateway()


def send_hitl_notification(hitl_id, user_wa: str | None = None) -> dict[str, Any]:
    """Kirim notifikasi approval HITL ke satu nomor WA.

    ``hitl_id`` boleh id (int) atau objek ``AIHitlQueue``. Return selalu dict
    (tidak pernah throw) agar pemanggil tidak gagal karena masalah WA.
    """
    if isinstance(hitl_id, int):
        from integrations.ai_agent.models import AIHitlQueue

        hitl = AIHitlQueue.objects.filter(pk=hitl_id).first()
        if hitl is None:
            return {"ok": False, "error": "not_found", "message_id": None}
    else:
        hitl = hitl_id

    from integrations.wa_bot.hitl_messages import send_hitl_notification as _send

    return _send(hitl, recipient=user_wa)
