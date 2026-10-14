"""Kelas dasar agent simulasi — fase M3.

``BaseAgent`` menyatukan tiga hal yang dipakai **semua** agent (scripted maupun
LLM) supaya tidak diduplikasi:

* **penegakan whitelist** (:meth:`_check_tool`) — satu-satunya tempat ``tool_set``
  diperiksa; di luar daftar → ``PermissionError`` (fail-closed);
* **substitusi path** (:meth:`_substitute`) — mengisi ``{key}`` dari payload
  dengan fallback ``id`` → ``order_id`` → ``order_ref`` → ``"0"``;
* **pemanggilan + telemetry** (:meth:`_call`) — ukur latency, panggil klien,
  catat ke ``Recorder`` (atau ``record_error`` lalu re-raise).

``BaseAgent`` bukan ``ABC`` formal (sengaja — belum perlu), tetapi :meth:`act`
**wajib** di-override subclass; implementasi dasar melempar ``NotImplementedError``.
Tidak ada state yang dipersist: hanya ``memory`` (deque in-memory) & ``state``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from ..client.http import MESClient
from ..llm.client import OllamaClient
from ..telemetry.recorder import Recorder
from ..world.events import Event

if TYPE_CHECKING:  # anotasi tipe saja — tidak memanggil httpx langsung
    import httpx

logger = logging.getLogger(__name__)

__all__ = ("AgentState", "BaseAgent")

#: Status siklus hidup agent (dipakai untuk prompt LLM & observability).
AgentState = Literal["idle", "working", "waiting"]

#: Placeholder ``{nama}`` di path tool_set (mis. ``/garmen/orders/{id}/...``).
_PATH_TOKEN = re.compile(r"\{(\w+)\}")

#: Pengganti sementara placeholder saat membangun regex whitelist.
_WILD = "w0rldw1ld"


def _to_regex(template: str) -> "re.Pattern[str]":
    """Ubah template path (``{x}`` = wildcard satu segmen) menjadi regex anchored."""

    tmp = re.sub(r"\{[^}]*\}", _WILD, template)
    escaped = re.escape(tmp).replace(_WILD, r"[^/]+")
    return re.compile("^" + escaped + "$")


class BaseAgent:
    """Perilaku bersama agent: whitelist, substitusi, pemanggilan + telemetry."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        client: MESClient,
        recorder: Recorder,
        tool_set: list[str],
        llm_client: Optional[OllamaClient] = None,
        bundle_registry=None,
    ) -> None:
        self.id = agent_id
        self.role = role
        self.client = client
        self.recorder = recorder
        self.tool_set = list(tool_set)
        self.llm_client = llm_client
        self.llm_enabled = llm_client is not None
        self.line_id: Optional[str] = None
        self.wc_id: Optional[str] = None
        self.memory: deque = deque(maxlen=10)
        self.state: AgentState = "idle"
        #: Registry bundle SHARED antar agent (di-set orchestrator setelah build).
        #: Update state di satu agent langsung terlihat agent lain (anti-stale).
        #: Tipe: ``orchestrator.BundleRegistry`` (duck-typed → hindari import melingkar).
        self.bundle_registry = bundle_registry
        #: Jeda realistis (FASE 2.7) — di-set orchestrator dari ``scenario.timing``.
        self.timing = None
        self.last_action_at: "Optional[datetime]" = None
        self._rng = random.Random()

    @property
    def available_bundles(self) -> list:
        """Backward-compat: daftar bundle dari registry (atau ``[]``)."""

        return self.bundle_registry.all() if self.bundle_registry is not None else []

    # ------------------------------------------------------------- whitelist
    def _check_tool(self, path: str) -> None:
        """Pastikan ``path`` diizinkan ``tool_set``; selain itu ``PermissionError``.

        Cocok bila string **sama persis** ATAU pola ``{...}`` (regex satu segmen)
        cocok dengan salah satu entri whitelist (dua arah: template↔konkret).
        Ini **satu-satunya** tempat whitelist ditegakkan.
        """

        for entry in self.tool_set:
            if entry == path:
                return
            if _to_regex(entry).match(path) or _to_regex(path).match(entry):
                return
        raise PermissionError(
            f"Agent {self.id} ({self.role}) tidak berwenang memanggil {path!r}; "
            f"tool_set={self.tool_set}"
        )

    # ------------------------------------------------------------ substitusi
    @staticmethod
    def _substitute(path: str, payload: Optional[dict]) -> str:
        """Isi token ``{nama}`` di path dari ``payload``.

        Fallback urut: ``nama`` → ``id`` → ``order_id`` → ``order_ref`` → ``"0"``.
        """

        data = payload or {}

        def _repl(match: "re.Match[str]") -> str:
            key = match.group(1)
            for candidate in (key, "id", "order_id", "order_ref"):
                if candidate in data:
                    return str(data[candidate])
            return "0"

        return _PATH_TOKEN.sub(_repl, path)

    # -------------------------------------------------------------- LLM helper
    @staticmethod
    def _parse_llm_json(text: str) -> dict:
        """Parse JSON dari output LLM (toleran fence markdown). Gagal → ``{}``."""

        if not text:
            return {}
        raw = str(text).strip()
        if raw.startswith("```"):
            raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
            if raw[:4].lower() == "json":
                raw = raw[4:].strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _version_for_path(self, path: str) -> "Optional[str]":
        """Version bundle untuk ``path`` aksi (id di ``/bundles/<id>/``).

        ``None`` bila path bukan aksi bundle atau id tak ada di registry (maka
        header ``X-Base-Version`` tidak dikirim).
        """

        match = re.search(r"/bundles/([^/]+)/", path)
        if not match:
            return None
        bundle = self._find_bundle(match.group(1))
        return bundle.get("version") if bundle else None

    # ------------------------------------------------------------ state bundle
    @staticmethod
    def _as_key(bundle_id):
        """Normalisasi id bundle → ``int`` bila memungkinkan (registry berkunci int)."""

        try:
            return int(bundle_id)
        except (TypeError, ValueError):
            return bundle_id

    def _find_bundle(self, bundle_id) -> "Optional[dict]":
        """Bundle dengan ``id`` tertentu dari registry (atau ``None``)."""

        if self.bundle_registry is None:
            return None
        return self.bundle_registry.get(self._as_key(bundle_id))

    def update_bundle_state(self, bundle_id, new_state, new_version=None) -> None:
        """Perbarui ``state``/``version`` bundle di registry (SHARED antar agent).

        Dipakai setelah aksi sukses (response 200) supaya agent lain melihat state
        terbaru (anti-stale). Registry tidak ada / bundle tak ditemukan → diabaikan.
        """

        if new_state is None or self.bundle_registry is None:
            return
        kwargs = {"state": new_state}
        if new_version:
            kwargs["version"] = new_version
        self.bundle_registry.update(self._as_key(bundle_id), **kwargs)

    async def refresh_bundle(self, bundle_id) -> "Optional[dict]":
        """GET detail bundle → update registry (state/version/allowed_actions).

        FASE 2.6 (multi-step): endpoint detail ``GET /garmen/bundles/<id>/`` memuat
        ``allowed_actions`` BARU sehingga bundle bisa di-action lagi dalam satu run.
        Return bundle baru (dict) atau ``None`` kalau gagal.
        """

        key = self._as_key(bundle_id)
        try:
            response = await self.client.get(f"/garmen/bundles/{key}/")
        except Exception as exc:  # noqa: BLE001 - refresh tak boleh mematikan run
            logger.warning("%s: refresh bundle %s gagal (%s).", self.id, key, exc)
            return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - body bukan JSON
            return None
        if not isinstance(body, dict):
            return None

        if self.bundle_registry is not None:
            updates: dict = {}
            for field in ("state", "version"):
                if body.get(field) is not None:
                    updates[field] = body[field]
            if isinstance(body.get("allowed_actions"), list):
                updates["allowed_actions"] = body["allowed_actions"]
            # FASE 3.3 — `current_work_center_code` display/KPI saja; `None` valid
            # (bundle tanpa WC), jadi dicek keberadaan key-nya, bukan nilainya.
            if "current_work_center_code" in body:
                updates["current_work_center_code"] = body["current_work_center_code"]
            if updates:
                self.bundle_registry.update(key, **updates)
        return self._find_bundle(key)

    async def _sync_bundle_state_from_response(self, path: str, response) -> None:
        """Sinkron state/version dari body aksi + **refresh** ``allowed_actions``.

        FASE 2.6: setelah aksi sukses, ambil ``allowed_actions`` baru via
        :meth:`refresh_bundle` supaya bundle bisa di-action lagi (multi-step).
        Kalau refresh gagal → kosongkan ``allowed_actions`` (fail-safe: agent lain
        skip, tidak menembak aksi usang → 400).
        """

        match = re.search(r"/bundles/([^/]+)/", path)
        if not match:
            return
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - body bukan JSON / kosong
            return
        if not isinstance(body, dict) or body.get("state") is None:
            return
        key = self._as_key(match.group(1))
        self.update_bundle_state(key, body.get("state"), body.get("version"))

        refreshed = await self.refresh_bundle(key)
        if refreshed is None and self.bundle_registry is not None:
            self.bundle_registry.update(key, allowed_actions=[])

    # -------------------------------------------------------------- telemetry
    def _log_decision(
        self,
        endpoint: str,
        method: str,
        status_code: Optional[int],
        latency_ms: float,
        decision_source: str,
        payload: Optional[dict] = None,
    ) -> None:
        """Catat keputusan ke ``Recorder`` + perbarui ``state`` & ``memory``."""

        self.recorder.record(
            agent_id=self.id,
            endpoint=endpoint,
            method=method,
            payload=payload,
            status_code=status_code,
            latency_ms=latency_ms,
            trace_id=self.client.last_trace_id,
            decision_source=decision_source,
        )
        self.state = "working"
        self.memory.append(
            {
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "decision_source": decision_source,
            }
        )

    # ------------------------------------------------------------------- aksi
    async def act(self, event: Event) -> "Optional[httpx.Response]":
        """Reaksi ke ``event`` — **wajib** di-override subclass."""

        raise NotImplementedError

    async def _call(
        self,
        endpoint: str,
        method: str,
        payload: Optional[dict],
        decision_source: str,
    ) -> "Optional[httpx.Response]":
        """Whitelist → substitusi → (idle/delay) → panggil → catat; error di-re-raise.

        FASE 2.7: idle/delay dilakukan **sebelum** HTTP tapi **sesudah** keputusan
        LLM (caller memanggil ``_call`` setelah LLM). Idle → ``None`` (skip).
        """

        self._check_tool(endpoint)
        method = method.upper()
        if method not in ("GET", "POST"):
            raise ValueError(
                f"Method tidak didukung: {method!r} (endpoint {endpoint!r})."
            )

        _, _, path_template = endpoint.partition(" ")
        path = self._substitute(path_template, payload)

        # Opsional (optimistic lock): kirim X-Base-Version untuk aksi bundle
        # kalau version-nya diketahui. Tidak ada → Django lewati cek konflik.
        headers: dict = {}
        if "/BUNDLE_" in path:
            version = self._version_for_path(path)
            if version:
                headers["X-Base-Version"] = str(version)

        # Endpoint AKSI bundle: Django menolak body berisi field tak dikenal → kirim
        # body KOSONG. Payload event tetap direkam ke recorder (audit) tapi TIDAK
        # dikirim ke Django (MVP: belum mengirim {"fields", "version"}).
        request_body = {} if (method == "POST" and "/BUNDLE_" in path) else payload

        # FASE 2.7 — jeda realistis (sebelum HTTP, sesudah keputusan LLM).
        if self.timing is not None and self._rng.random() < self.timing.idle_prob:
            logger.info("%s: idle (skip %s %s).", self.id, method, path)
            return None
        if self.timing is not None and self.last_action_at is not None:
            elapsed = (datetime.utcnow() - self.last_action_at).total_seconds()
            delay = self._rng.uniform(
                self.timing.min_delay_sec, self.timing.max_delay_sec
            )
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)

        started = time.perf_counter()
        try:
            if method == "GET":
                response = await self.client.get(path, headers=headers or None)
            else:
                response = await self.client.post(
                    path, json=request_body, headers=headers or None
                )
        except Exception as exc:  # noqa: BLE001 - catat dulu, lalu teruskan
            self.recorder.record_error(self.id, path, str(exc), self.client.last_trace_id)
            self.state = "waiting"
            raise

        self.last_action_at = datetime.utcnow()

        # Aksi bundle sukses → sinkron state/version + refresh allowed_actions.
        if response.status_code == 200 and "/BUNDLE_" in path:
            await self._sync_bundle_state_from_response(path, response)

        latency_ms = (time.perf_counter() - started) * 1000.0
        self._log_decision(
            path, method, response.status_code, latency_ms, decision_source, payload
        )
        return response
