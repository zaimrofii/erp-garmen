"""Eksekusi aksi setelah HITL approved (S.5) — LOG-ONLY, bukan write.

AI tidak pernah menulis data produksi. Executor hanya mencatat aksi yang sudah
disetujui manusia dan mengembalikan pesan; eksekusi nyata tetap supervisor
lewat UI existing (fase berikutnya bila ingin integrasi service).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Map pola aksi → fungsi executor (semua hanya log + pesan).
ACTION_MAP = {
    "rework": "_execute_rework",
    "pindah": "_execute_move_bundle",
    "audit": "_execute_audit",
    "hentikan": "_execute_pause",
}


def _action_text(hitl) -> str:
    """Ambil aksi pertama (mendukung payload `actions[]` S.1 dan `action` lama)."""
    payload = hitl.proposed_action if isinstance(hitl.proposed_action, dict) else {}

    actions = payload.get("actions")
    if isinstance(actions, list):
        for item in actions:
            if isinstance(item, dict):
                text = str(item.get("action") or "").strip()
                if text:
                    return text

    return str(payload.get("action") or payload.get("type") or "").strip()


def execute(hitl_id: int) -> dict:
    """Eksekusi aksi dari AIHitlQueue yang APPROVED.

    Return ``{"ok", "executed", "message"}``; status bukan APPROVED ditolak.
    """
    from integrations.ai_agent.models import AIHitlQueue

    hitl = AIHitlQueue.objects.filter(pk=hitl_id).first()
    if hitl is None:
        return {"ok": False, "error": "not_found"}

    if hitl.status != "APPROVED":
        return {"ok": False, "error": "not_approved", "status": hitl.status}

    action = _action_text(hitl)
    action_lower = action.lower()

    for pattern, func_name in ACTION_MAP.items():
        if pattern in action_lower:
            func = globals().get(func_name)
            if func is not None:
                try:
                    message = func(hitl)
                except Exception as exc:  # noqa: BLE001 - executor tidak boleh crash
                    logger.exception("HITL #%s: executor %s gagal.", hitl_id, func_name)
                    return {"ok": False, "error": str(exc), "action": action}
                return {
                    "ok": True,
                    "executed": True,
                    "action": action,
                    "message": message,
                }

    logger.warning("HITL #%s: aksi %r tidak dikenal, skip.", hitl_id, action)
    return {
        "ok": True,
        "executed": False,
        "action": action,
        "message": "Aksi tidak ada executor, hanya dicatat",
    }


def _execute_rework(hitl) -> str:
    logger.info("HITL #%s: rework action logged", hitl.pk)
    return "Rework dicatat, supervisor akan eksekusi manual"


def _execute_move_bundle(hitl) -> str:
    logger.info("HITL #%s: move bundle action logged", hitl.pk)
    return "Pindah bundle dicatat, supervisor akan eksekusi manual"


def _execute_audit(hitl) -> str:
    logger.info("HITL #%s: audit action logged", hitl.pk)
    return "Audit dicatat, supervisor akan lakukan audit"


def _execute_pause(hitl) -> str:
    logger.info("HITL #%s: pause action logged", hitl.pk)
    return "Pause dicatat, supervisor akan eksekusi manual"


__all__ = ("ACTION_MAP", "execute")
