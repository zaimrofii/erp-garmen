"""Agent QC — pilih aksi QC dari ``allowed_actions`` bundle (fase M3/M5).

FASE 2.3: QC membaca ``allowed_actions`` bundle (dari bootstrap Django).
``BUNDLE_QC`` diprioritaskan, lalu ``BUNDLE_SCRAP``; tak ada keduanya → skip.
Helper LLM (``_decide``/``ACTION_TO_TOOL``) disimpan sebagai jalur alternatif
tapi belum dipakai di MVP ini. Tidak ada state yang dipersist.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from ..llm.client import OllamaError
from ..world.events import Event
from .base import BaseAgent

if TYPE_CHECKING:  # anotasi tipe saja
    import httpx

logger = logging.getLogger(__name__)

__all__ = ("QCAgent",)


class QCAgent(BaseAgent):
    """QC: event DEFECT → aksi (LLM, fallback rework) → endpoint → client."""

    ROLE = "qc"
    #: Event yang relevan untuk QC (selain ini → idle/None).
    RELEVANT_EVENTS = ("DEFECT",)
    #: Aksi yang sah dari LLM.
    VALID_ACTIONS = ("REWORK", "SCRAP")
    #: Aksi fallback bila output LLM tidak valid / LLM gagal (lebih aman).
    FALLBACK_ACTION = "REWORK"
    #: Aksi QC yang sah pada bundle (dari ``allowed_actions``); QC diprioritaskan.
    QC_ACTIONS = ("BUNDLE_QC", "BUNDLE_SCRAP")
    SYSTEM_PROMPT = (
        'Kamu QC garmen. Jawab HANYA JSON '
        '{"action": "REWORK|SCRAP", "reason": "..."}'
    )

    def __init__(self, agent_id, client, recorder, tool_set, llm_client=None):
        if llm_client is None:
            raise ValueError("QCAgent butuh llm_client (peran ini memakai LLM).")
        super().__init__(
            agent_id, self.ROLE, client, recorder, tool_set, llm_client=llm_client
        )

    # ---------------------------------------------------------------- mapping
    #: Aksi LLM → endpoint aksi BUNDLE eksekutabel (aksi eksak state machine).
    ACTION_TO_TOOL = {
        "REWORK": "POST /garmen/bundles/{id}/BUNDLE_QC/",
        "SCRAP": "POST /garmen/bundles/{id}/BUNDLE_SCRAP/",
    }

    def _action_to_endpoint(self, action: str) -> Optional[str]:
        """Map aksi LLM (REWORK/SCRAP) → endpoint aksi bundle."""

        return self.ACTION_TO_TOOL.get(action)

    @classmethod
    def _pick_action(cls, allowed_actions: list) -> Optional[str]:
        """Aksi QC dari ``allowed_actions`` (prioritas ``BUNDLE_QC``), else ``None``."""

        ids = [
            item.get("id") for item in (allowed_actions or []) if isinstance(item, dict)
        ]
        for action_id in cls.QC_ACTIONS:
            if action_id in ids:
                return action_id
        return None

    @staticmethod
    def _parse_action(raw: str) -> Optional[str]:
        """Parse output LLM → aksi (``None`` bila JSON rusak / aksi di luar daftar)."""

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        action = str(data.get("action", "")).strip().upper() if isinstance(data, dict) else ""
        return action if action in QCAgent.VALID_ACTIONS else None

    async def _decide(self, payload: dict) -> tuple[str, str]:
        """Tentukan (action, decision_source) lewat LLM, dengan fallback scripted."""

        bundle_id = payload.get("bundle_id", payload.get("id", "0"))
        defect_type = payload.get("defect_type", "unknown")
        qty = payload.get("qty", 0)
        user = f"Bundle {bundle_id}, defect: {defect_type}, qty: {qty}."
        try:
            raw = await self.llm_client.chat(self.SYSTEM_PROMPT, user, json_mode=True)
        except OllamaError as exc:
            logger.warning(
                "qc %s: LLM gagal (%s) -> fallback scripted %s",
                self.id, exc, self.FALLBACK_ACTION,
            )
            return self.FALLBACK_ACTION, "scripted"

        action = self._parse_action(raw)
        if action is None:
            logger.warning(
                "qc %s: output LLM tidak valid (%r) -> fallback %s",
                self.id, raw, self.FALLBACK_ACTION,
            )
            return self.FALLBACK_ACTION, "llm"
        return action, "llm"

    # ------------------------------------------------------------------- aksi
    async def act(self, event: Event) -> "Optional[httpx.Response]":
        """Proses ``DEFECT`` (LLM putuskan REWORK/SCRAP, divalidasi allowed_actions).

        FASE 2.8: kalau LLM aktif, ia memutuskan REWORK/SCRAP. Keputusan itu
        divalidasi terhadap ``allowed_actions``: kalau aksi target tidak tersedia →
        fallback ke aksi QC apa pun yang ada (atau skip).
        """

        if getattr(event, "type", None) not in self.RELEVANT_EVENTS:
            return None

        payload = dict(getattr(event, "payload", None) or {})
        bundle_id = payload.get("bundle_id")
        if bundle_id in (None, ""):
            logger.warning("qc %s: event DEFECT tanpa bundle_id -> skip.", self.id)
            return None

        bundle = self._find_bundle(bundle_id)
        if bundle is None:
            logger.warning(
                "qc %s: bundle %s tak ada di registry -> skip.", self.id, bundle_id
            )
            return None

        allowed = bundle.get("allowed_actions") or []
        if not allowed:
            logger.info(
                "qc %s: bundle %s tanpa allowed_actions -> skip.", self.id, bundle_id
            )
            return None

        # LLM: REWORK atau SCRAP? (reaktif sejak FASE 2.8; fallback: REWORK).
        decision_source = "scripted"
        llm_action = "REWORK"
        if self.llm_enabled and self.llm_client is not None:
            decision_source = "llm"
            llm_action = await self._llm_decide(payload)

        target = "BUNDLE_SCRAP" if llm_action == "SCRAP" else "BUNDLE_QC"

        # Validasi keputusan LLM terhadap allowed_actions; fallback bila tak ada.
        allowed_ids = [a.get("id") for a in allowed if isinstance(a, dict)]
        if target not in allowed_ids:
            fallback = self._pick_action(allowed)
            if fallback is None:
                logger.info(
                    "qc %s: LLM=%s tapi tak ada aksi QC di allowed_actions -> skip.",
                    self.id, llm_action,
                )
                return None
            target = fallback

        endpoint = f"POST /garmen/bundles/{bundle_id}/{target}/"
        method, _, _ = endpoint.partition(" ")
        return await self._call(endpoint, method.upper(), {"id": bundle_id}, decision_source)

    async def _llm_decide(self, payload: dict) -> str:
        """Tanya LLM REWORK/SCRAP. Gagal / tak valid → ``"REWORK"`` (fail-safe)."""

        bundle_id = payload.get("bundle_id")
        defect_type = payload.get("defect_type", "unknown")
        qty = payload.get("qty", 0)
        prompt = (
            f"Bundle {bundle_id}. Defect: {defect_type}, qty: {qty}. "
            f'REWORK atau SCRAP? JSON: {{"action": "REWORK"|"SCRAP"}}'
        )
        try:
            resp = await self.llm_client.chat("Kamu QC garmen.", prompt, json_mode=True)
        except OllamaError as exc:
            logger.warning("qc %s: LLM gagal (%s) -> REWORK (fail-safe).", self.id, exc)
            return "REWORK"
        parsed = self._parse_llm_json(resp)
        action = str(parsed.get("action", "REWORK")).strip().upper()
        return action if action in ("REWORK", "SCRAP") else "REWORK"
