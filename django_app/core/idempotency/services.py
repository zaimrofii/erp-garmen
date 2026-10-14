"""IdempotencyService — cek & simpan hasil aksi idempotent (kontrak §5.1).

Aturan:

  * key kosong -> `check()` mengembalikan `None` (request tanpa Idempotency-Key
    tetap diproses, sesuai kontrak §10 — hanya dicatat di log oleh pemanggil);
  * key ada + **semua** (resource, resource_id, action, request_hash) cocok +
    belum kedaluwarsa -> record dikembalikan (replay);
  * key ada tapi salah satu beda -> dianggap request baru (+ log warning);
  * record kedaluwarsa -> dihapus lalu dianggap request baru.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import IdempotencyRecord

logger = logging.getLogger(__name__)

#: Umur default record (24 jam) — cukup untuk retry jaringan di lantai produksi.
DEFAULT_TTL_SECONDS = 86400


class IdempotencyService:
    """Akses IdempotencyRecord (stateless; seluruh state ada di DB)."""

    def check(
        self,
        key: str | None,
        resource: str,
        resource_id: Any,
        action: str,
        request_hash: str,
    ) -> IdempotencyRecord | None:
        """Record replay untuk key ini, atau `None` kalau harus dieksekusi baru."""
        if not key:
            return None

        record = IdempotencyRecord.objects.filter(key=str(key)).first()
        if record is None:
            return None

        if self._is_expired(record):
            logger.info("idempotency: key '%s' kedaluwarsa -> dihapus.", key)
            record.delete()
            return None

        if not self._matches(record, resource, resource_id, action, request_hash):
            logger.warning(
                "idempotency: key '%s' dipakai untuk request berbeda "
                "(tersimpan: %s#%s:%s) -> diperlakukan sebagai request baru.",
                key,
                record.resource,
                record.resource_id,
                record.action,
            )
            return None

        return record

    def save(
        self,
        key: str,
        resource: str,
        resource_id: Any,
        action: str,
        request_hash: str,
        response_status: int,
        response_body: dict | None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> IdempotencyRecord:
        """Simpan (create atau update) hasil eksekusi sebuah key."""
        try:
            ttl = int(ttl_seconds)
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SECONDS
        expires_at = timezone.now() + timedelta(seconds=ttl)

        record, created = IdempotencyRecord.objects.update_or_create(
            key=str(key),
            defaults={
                "resource": str(resource),
                "resource_id": str(resource_id),
                "action": str(action),
                "request_hash": str(request_hash),
                "response_status": int(response_status),
                "response_body": dict(response_body or {}),
                "expires_at": expires_at,
            },
        )
        logger.info(
            "idempotency: key '%s' %s (%s#%s:%s).",
            key,
            "disimpan" if created else "diperbarui",
            resource,
            resource_id,
            action,
        )
        return record

    def cleanup_expired(self) -> int:
        """Hapus record kedaluwarsa; return jumlah baris (dipanggil Celery beat nanti)."""
        deleted, _ = IdempotencyRecord.objects.filter(
            expires_at__lt=timezone.now()
        ).delete()
        logger.info("idempotency: %s record kedaluwarsa dihapus.", deleted)
        return deleted

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _is_expired(record: IdempotencyRecord) -> bool:
        return bool(record.expires_at and record.expires_at <= timezone.now())

    @staticmethod
    def _matches(
        record: IdempotencyRecord,
        resource: str,
        resource_id: Any,
        action: str,
        request_hash: str,
    ) -> bool:
        return (
            record.resource == str(resource)
            and record.resource_id == str(resource_id)
            and record.action == str(action)
            and record.request_hash == str(request_hash)
        )
