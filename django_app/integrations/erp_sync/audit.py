"""Helper audit untuk **push ERP** (WIP/FG/SCRAP/INVOICE) — fase I8.11.

Sebelumnya ``AuditLog`` hanya ditulis oleh **endpoint** sync di
``integrations/erp_sync/api.py`` (action ``SYNC_WIP``/``SYNC_FG``), sedangkan
**task** & **service** yang benar-benar mengirim stok ke ERP (``tasks.py`` →
``_push_stage``, ``services/scrap_sync.py``, ``services/invoice_sync.py``) tidak
meninggalkan jejak apa pun. Akibatnya pertanyaan "stok ini sudah dikirim belum,
dan dengan ``erp_id`` apa?" hanya bisa dijawab dari ``SyncRecord``.

Modul ini menutup celah itu **tanpa** mengubah model ``AuditLog`` (dipakai
apa adanya) dan **tanpa** mengubah adapter bisnis: setiap percobaan kirim yang
nyata (status ``sent``/``failed``) dicatat dengan format:

    action      : "erp_sync.push_wip" | "erp_sync.push_fg"
                  | "erp_sync.push_scrap" | "erp_sync.push_invoice"
    resource    : resource MES ("work_order", "bundle", "scrap_accumulator", "order")
    resource_id : id resource MES
    result      : AuditLog.Result.OK (sent) | FAILED
    metadata    : {"status", "erp_id", "error", "task_id"}

**Best-effort**: kegagalan menulis audit **tidak** menggagalkan push (yang
penting stoknya terkirim & ``SyncRecord``-nya benar) — exception di sini hanya
di-log, pola yang sama dengan ``SyncOdooView._audit``. Percobaan yang
**dilewati** karena record sudah ``SENT``/``DUPLICATE`` sengaja **tidak**
diaudit supaya log tidak banjir saat task di-retry/dijalankan berulang
(idempotensi sudah terekam di ``SyncRecord``).
"""

from __future__ import annotations

import logging
from typing import Any

from core.audit.models import AuditLog
from core.audit.services import AuditLogger

logger = logging.getLogger(__name__)

__all__ = ("log_push",)

#: Action audit per stage (dipakai ``_push_stage`` di ``tasks.py``).
ACTION_WIP = "erp_sync.push_wip"
ACTION_FG = "erp_sync.push_fg"
ACTION_SCRAP = "erp_sync.push_scrap"
ACTION_INVOICE = "erp_sync.push_invoice"

#: Status yang berarti percobaan kirim nyata (selain ini tidak diaudit).
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


def log_push(
    action: str,
    resource: str,
    resource_id: Any,
    *,
    status: str,
    erp_id: Any = None,
    error: Any = None,
    task_id: Any = None,
    payload: dict | None = None,
) -> None:
    """Catat satu percobaan push ERP ke ``AuditLog`` (best-effort, tanpa raise).

    ``status`` = ``"sent"`` → ``result=OK``, selain itu → ``result=FAILED``.
    ``erp_id``/``error``/``task_id`` disimpan di ``metadata`` (JSON-safe lewat
    ``AuditLogger``); ``payload`` = data yang dikirim ke adapter.
    """
    result = AuditLog.Result.OK if str(status) == STATUS_SENT else AuditLog.Result.FAILED
    metadata = {
        "status": str(status),
        "erp_id": erp_id,
        "error": error,
        "task_id": task_id,
    }
    try:
        AuditLogger().log(
            user=None,  # dipicu task/sistem, bukan user request
            action=str(action),
            resource=str(resource),
            resource_id=resource_id,
            payload=dict(payload or {}),
            result=result,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan push
        logger.exception(
            "audit push gagal: action=%s %s#%s (status=%s).",
            action,
            resource,
            resource_id,
            status,
        )
