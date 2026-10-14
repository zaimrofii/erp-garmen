"""Agent operator — pilih aksi bundle dari ``allowed_actions`` (fase M3/M5).

FASE 2.3: operator **tidak** menebak/hardcode aksi. Ia membaca
``allowed_actions`` bundle (data dari Django via bootstrap), memilih aksi "normal"
pertama (BUNDLE_START/ADVANCE/QC/FINISH; ``BUNDLE_SCRAP`` dilewati), lalu
mengirim ``POST /garmen/bundles/<id>/<ACTION>/`` (body ``{}`` + X-Base-Version).
Helper LLM (``_decide``/``ACTION_TO_TOOL``) disimpan sebagai jalur alternatif tapi
belum dipakai di MVP ini. Tidak ada state yang dipersist.
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

__all__ = ("OperatorAgent",)


class OperatorAgent(BaseAgent):
    """Operator lini: event → aksi (LLM, fallback scripted) → endpoint → client."""

    ROLE = "operator"
    #: Event yang relevan untuk operator (selain ini → idle/None).
    RELEVANT_EVENTS = ("ORDER_IN", "BUNDLE_ASSIGNED")
    #: Aksi yang sah dari LLM.
    VALID_ACTIONS = ("START", "FINISH", "SCRAP")
    #: Aksi fallback bila output LLM tidak valid / LLM gagal.
    FALLBACK_ACTION = "START"
    #: Aksi "operator-relevant" (``BUNDLE_SCRAP`` TIDAK di sini — itu pessimistic).
    OPERATOR_ACTIONS = ("BUNDLE_START", "BUNDLE_ADVANCE", "BUNDLE_QC", "BUNDLE_FINISH")
    SYSTEM_PROMPT = (
        'Kamu operator garmen. Jawab HANYA dengan JSON '
        '{"action": "START|FINISH|SCRAP", "reason": "..."}'
    )

    def __init__(self, agent_id, client, recorder, tool_set, llm_client=None):
        if llm_client is None:
            raise ValueError("OperatorAgent butuh llm_client (peran ini memakai LLM).")
        super().__init__(
            agent_id, self.ROLE, client, recorder, tool_set, llm_client=llm_client
        )

    # ---------------------------------------------------------------- mapping
    #: Aksi LLM → endpoint aksi BUNDLE eksekutabel (aksi eksak state machine).
    ACTION_TO_TOOL = {
        "START": "POST /garmen/bundles/{id}/BUNDLE_START/",
        "FINISH": "POST /garmen/bundles/{id}/BUNDLE_FINISH/",
        "SCRAP": "POST /garmen/bundles/{id}/BUNDLE_SCRAP/",
    }

    def _action_to_endpoint(self, action: str) -> Optional[str]:
        """Map aksi LLM (START/FINISH/SCRAP) → endpoint aksi bundle."""

        return self.ACTION_TO_TOOL.get(action)

    @classmethod
    def _pick_action(cls, allowed_actions: list) -> Optional[str]:
        """Aksi pertama dari ``allowed_actions`` yang operator-relevant (else ``None``).

        MVP (FASE 2.3): pilihan aksi **rule-based** dari ``allowed_actions`` Django
        (bukan LLM); ``BUNDLE_SCRAP`` dilewati. Tak ada aksi relevant → ``None``.
        """

        for item in allowed_actions or []:
            action_id = item.get("id") if isinstance(item, dict) else None
            if action_id in cls.OPERATOR_ACTIONS:
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
        return action if action in OperatorAgent.VALID_ACTIONS else None

    async def _decide(self, payload: dict) -> tuple[str, str]:
        """Tentukan (action, decision_source) lewat LLM, dengan fallback scripted."""

        bundle_id = payload.get("bundle_id", payload.get("id", "0"))
        wc = self.wc_id or payload.get("wc_id") or payload.get("work_center", "?")
        user = f"Kamu operator. Bundle {bundle_id} di WC {wc}. Aksi: START/FINISH/SCRAP."
        try:
            raw = await self.llm_client.chat(self.SYSTEM_PROMPT, user, json_mode=True)
        except OllamaError as exc:
            logger.warning(
                "operator %s: LLM gagal (%s) -> fallback scripted %s",
                self.id, exc, self.FALLBACK_ACTION,
            )
            return self.FALLBACK_ACTION, "scripted"

        action = self._parse_action(raw)
        if action is None:
            logger.warning(
                "operator %s: output LLM tidak valid (%r) -> fallback %s",
                self.id, raw, self.FALLBACK_ACTION,
            )
            return self.FALLBACK_ACTION, "llm"
        return action, "llm"

    # ------------------------------------------------------------------- aksi
    async def act(self, event: Event) -> "Optional[httpx.Response]":
        """Proses ``BUNDLE_ASSIGNED`` (LLM putuskan kerjakan/skip + aksi rule-based).

        FASE 2.8: kalau LLM aktif, ia memutuskan **kerjakan atau skip**
        (``{"work": bool}``); pilihan aksi TETAP rule-based dari ``allowed_actions``
        (LLM tidak memilih action). Bundle tak ada / terminal / tanpa
        ``allowed_actions`` / LLM bilang skip → **None**.
        """

        if getattr(event, "type", None) not in self.RELEVANT_EVENTS:
            return None

        payload = dict(getattr(event, "payload", None) or {})
        bundle_id = payload.get("bundle_id")
        if bundle_id in (None, ""):
            logger.warning(
                "operator %s: event %s tanpa bundle_id -> skip.",
                self.id, getattr(event, "type", "?"),
            )
            return None

        bundle = self._find_bundle(bundle_id)
        if bundle is None:
            logger.warning(
                "operator %s: bundle %s tak ada di registry -> skip.",
                self.id, bundle_id,
            )
            return None
        if bundle.get("state") in ("DONE", "CANCELLED"):
            logger.info(
                "operator %s: bundle %s state %s (terminal) -> skip.",
                self.id, bundle_id, bundle.get("state"),
            )
            return None

        allowed = bundle.get("allowed_actions") or []
        if not allowed:
            logger.info(
                "operator %s: bundle %s tanpa allowed_actions -> skip.",
                self.id, bundle_id,
            )
            return None

        # LLM: kerjakan atau skip? (reaktif sejak FASE 2.8; fallback: kerjakan).
        decision_source = "scripted"
        if self.llm_enabled and self.llm_client is not None:
            decision_source = "llm"
            if not await self._llm_should_work(bundle_id, bundle, allowed):
                return None

        # Rule-based: pilih aksi (divalidasi terhadap allowed_actions).
        action_id = self._pick_action(allowed)
        if action_id is None:
            logger.info(
                "operator %s: bundle %s tak punya aksi operator-relevant -> skip.",
                self.id, bundle_id,
            )
            return None

        endpoint = f"POST /garmen/bundles/{bundle_id}/{action_id}/"
        method, _, _ = endpoint.partition(" ")
        return await self._call(endpoint, method.upper(), {"id": bundle_id}, decision_source)

    async def _llm_should_work(self, bundle_id, bundle, allowed: list) -> bool:
        """Tanya LLM "kerjakan atau skip?". ``True`` = kerjakan (fail-safe)."""

        ids = [a.get("id") for a in allowed if isinstance(a, dict)]
        prompt = (
            f'Bundle {bundle_id} state {bundle.get("state")}. '
            f"Aksi tersedia: {ids}. Kerjakan? "
            f'JSON: {{"work": true|false, "reason": "..."}}'
        )
        try:
            resp = await self.llm_client.chat(
                "Kamu operator garmen.", prompt, json_mode=True
            )
        except OllamaError as exc:
            logger.warning(
                "operator %s: LLM gagal (%s) -> kerjakan (fail-safe).", self.id, exc
            )
            return True
        parsed = self._parse_llm_json(resp)
        if not parsed.get("work", True):
            logger.info(
                "operator %s: LLM putuskan skip bundle %s: %s",
                self.id, bundle_id, parsed.get("reason", ""),
            )
            return False
        return True
