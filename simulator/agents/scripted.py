"""Agent scripted (rule-based) — cutting/inventory/ppic — fase M2/M3.

Hanya **operator** & **qc** yang memakai LLM (lihat ``roles_using_llm``); peran
pendukung lantai produksi aksinya deterministik → cukup script. Agent ini
menerjemahkan *event dunia* menjadi *pemanggilan endpoint* lewat whitelist
(``tool_set``); sejak M3 penegakan whitelist, substitusi path, dan pemanggilan +
telemetry hidup di :class:`~simulator.agents.base.BaseAgent`.

Agent **tidak** memanggil LLM dan **tidak** mengimpor ``httpx`` langsung — semua
I/O lewat :class:`~simulator.client.http.MESClient` (mudah di-mock & diaudit).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Optional

from ..world.events import Event
from .base import BaseAgent

if TYPE_CHECKING:  # anotasi tipe saja — tidak memanggil httpx/klien langsung
    import httpx

    from ..client.http import MESClient
    from ..telemetry.recorder import Recorder

__all__ = ("ScriptedAgent",)

logger = logging.getLogger(__name__)

#: Peran yang aksinya deterministik (scripted), bukan LLM.
ScriptedRole = Literal["cutting", "inventory", "ppic"]


class ScriptedAgent(BaseAgent):
    """Agent rule-based: event → endpoint (whitelist) → client → recorder.

    Hanya tabel mapping yang tinggal di sini; whitelist/substitusi/pemanggilan &
    telemetry diwarisi dari :class:`~simulator.agents.base.BaseAgent`.
    """

    #: Tabel mapping ``(role, event.type)`` → ``"METHOD path"`` (bukan if-else panjang).
    #: FASE 3.4: ``cutting`` + ``ORDER_IN`` sengaja **TIDAK** ada di sini — alurnya
    #: 2 langkah (WorkOrder lalu Bundle) dan ditangani `act()` →
    #: :meth:`_handle_order_in`.
    EVENT_ENDPOINTS: dict[tuple[str, str], str] = {
        ("inventory", "ORDER_IN"): "GET /garmen/orders/{id}/readiness/",
        ("inventory", "DEFECT"): "POST /garmen/orders/{id}/recompute-readiness/",
        ("ppic", "ORDER_IN"): "POST /sync/odoo/WIP/",
        ("ppic", "URGENT"): "POST /sync/odoo/WIP/",
    }

    #: Endpoint yang WAJIB ada di ``tool_set`` cutting untuk alur ``ORDER_IN``.
    ORDER_IN_TOOLS: tuple[str, ...] = (
        "POST /garmen/work-orders/",
        "POST /garmen/bundles/",
    )

    #: Kandidat resource OrderLine di Django (urutan coba; pertama yang 200 menang).
    ORDER_LINE_PATHS: tuple[str, ...] = ("/garmen/order-lines/", "/garmen/orders/")

    #: Key produk pada respons OrderLine: resource `order-lines` mengirim
    #: `product_code`; sumber lain bisa mengirim `product`. Dua-duanya diterima.
    PRODUCT_KEYS: tuple[str, ...] = ("product_code", "product")

    #: Ukuran bundle default saat cutting memecah satu order line (FASE 3.4).
    DEFAULT_BUNDLE_SIZE = 10

    def __init__(
        self,
        agent_id: str,
        role: ScriptedRole,
        client: "MESClient",
        recorder: "Recorder",
        tool_set: list[str],
    ) -> None:
        super().__init__(agent_id, role, client, recorder, tool_set)
        #: Cache ``product_ref`` per bundle (FASE 3.1.2) → resolusi (2 RPC) hanya
        #: sekali per bundle per proses, bukan tiap aksi WIP.
        self._product_ref_cache: dict = {}

    # ---------------------------------------------------------------- mapping
    def _endpoint_for_event(self, event: Event) -> Optional[str]:
        """Endpoint ``"METHOD path"`` untuk ``(role, event.type)``; ``None`` = idle."""

        return self.EVENT_ENDPOINTS.get((self.role, getattr(event, "type", None)))

    # ------------------------------------------------------------------- aksi
    async def act(self, event: Event) -> "Optional[httpx.Response]":
        """Reaksi ke ``event``: panggil endpoint (whitelist) & catat telemetry.

        Return ``Response`` bila ada aksi, ``None`` bila event tidak relevan /
        peran dinonaktifkan (``tool_set`` kosong, mis. cutting/inventory) — idle,
        **bukan** error.

        FASE 3.4 — ``cutting`` + ``ORDER_IN`` memakai alur 2 langkah (buat
        WorkOrder lalu Bundle) lewat :meth:`_handle_order_in`, bukan satu endpoint
        statis seperti peran lain.
        """

        if self.role == "cutting" and getattr(event, "type", None) == "ORDER_IN":
            if not set(self.ORDER_IN_TOOLS) <= set(self.tool_set):
                return None  # role dinonaktifkan / tool_set belum lengkap → idle
            return await self._handle_order_in(event)

        endpoint = self._endpoint_for_event(event)
        if endpoint is None:
            return None
        # Role dinonaktifkan (tool_set kosong) → idle, jangan PermissionError.
        if endpoint not in self.tool_set:
            return None

        if self.role == "ppic" and "/sync/odoo/" in endpoint:
            body = await self._sync_wip_body()
            if body is None:
                return None  # tak ada bundle → skip
        else:
            body = dict(getattr(event, "payload", None) or {})

        method, _, _ = endpoint.partition(" ")
        return await self._call(endpoint, method.upper(), body, "scripted")

    async def _sync_wip_body(self) -> "Optional[dict]":
        """Body sync WIP dua-tahap: ``{resource, resource_id, payload}``.

        Bundle diambil dari ``self.available_bundles`` (bootstrap MES). Tidak ada
        bundle → ``None`` (agent skip, jangan kirim payload salah bentuk).

        FASE 3.1.1: ``payload`` WAJIB memuat ``product_ref`` (kontrak OdooAdapter
        ``push_wip_issue``). Kalau tak bisa di-resolve → ``"UNKNOWN"`` supaya Celery
        mencatat error yang JELAS (bukan payload cacat bentuk).
        """

        bundles = getattr(self, "available_bundles", None) or []
        if not bundles:
            return None
        bundle_id = bundles[0].get("id")
        if bundle_id in (None, ""):
            return None
        product_ref = await self._resolve_product_ref(bundle_id)
        return {
            "resource": "bundle",
            "resource_id": str(bundle_id),
            "payload": {
                "product_ref": product_ref,
                "qty": 1,
                "ref": f"WIP-{bundle_id}",
            },
        }

    async def _resolve_product_ref(self, bundle_id) -> str:
        """``product_ref`` bundle: bundle → work_order → product_code; fallback "UNKNOWN".

        FASE 3.1.2: bundle detail Django **tidak** mengekspos produk, jadi chaining:

        1. ``GET /garmen/bundles/<id>/`` → ``work_order_id`` (atau ``work_order``).
           Kalau detail memuat ``product_ref``/``product_code`` langsung, pakai itu.
        2. ``GET /garmen/work-orders/<wo_id>/`` → ``product_code``.
        3. Tidak ada / gagal → ``"UNKNOWN"`` (fail-closed — jangan skip WIP).

        Hasil di-cache di ``self._product_ref_cache`` (``bundle_id`` → ``product_ref``)
        supaya 2 RPC hanya dibayar sekali per bundle. Dibaca lewat klien LANGSUNG
        (bukan ``_call``) supaya tak kena penegakan ``tool_set`` ppic (hanya
        ``POST /sync/odoo/WIP/``).
        """

        key = str(bundle_id)
        if key in self._product_ref_cache:
            return self._product_ref_cache[key]
        product_ref = await self._fetch_product_ref(bundle_id)
        self._product_ref_cache[key] = product_ref
        return product_ref

    async def _fetch_product_ref(self, bundle_id) -> str:
        """Resolusi produk 2 RPC: bundle detail → work-order detail → ``product_code``."""

        bundle_detail = await self._get_json(f"/garmen/bundles/{bundle_id}/")
        if bundle_detail is None:
            return "UNKNOWN"

        direct = bundle_detail.get("product_ref") or bundle_detail.get("product_code")
        if direct:
            return str(direct)

        wo_id = bundle_detail.get("work_order_id") or bundle_detail.get("work_order")
        if wo_id in (None, ""):
            return "UNKNOWN"

        wo_detail = await self._get_json(f"/garmen/work-orders/{wo_id}/")
        if wo_detail is None:
            return "UNKNOWN"
        product_code = wo_detail.get("product_code")
        if product_code:
            return str(product_code)
        return "UNKNOWN"

    async def _get_json(self, path: str) -> "Optional[dict]":
        """GET ``path`` → dict JSON; ``None`` kalau gagal / status != 200 / non-dict."""

        try:
            response = await self.client.get(path)
        except Exception:  # noqa: BLE001 - gagal baca detail != gagalkan WIP
            return None
        if response.status_code != 200:
            return None
        try:
            detail = response.json()
        except Exception:  # noqa: BLE001 - respons tak terduga
            return None
        return detail if isinstance(detail, dict) else None

    # --------------------------------------------------------- FASE 3.4 (order)
    async def _handle_order_in(self, event: Event) -> "Optional[httpx.Response]":
        """``ORDER_IN`` (FASE 3.4): OrderLine -> WorkOrder -> Bundle (2 POST).

        Alur:

        1. cari OrderLine di Django (:meth:`_find_order_line`) — tak ada → skip;
        2. ``POST /garmen/work-orders/`` ``{order_line_id}`` -> 201 + id WO;
        3. ``POST /garmen/bundles/`` ``{work_order_id, size_matrix, bundle_size}``.

        Kedua POST lewat :meth:`BaseAgent._call` (whitelist + telemetry → 2 baris
        rekaman). Jeda/idle realistis **dimatikan sementara** untuk 2 langkah ini
        supaya alur tidak terputus di tengah (WO jadi tapi bundle batal → WO yatim
        yang membuat percobaan berikutnya ditolak 400 oleh endpoint create).
        """

        line = await self._find_order_line()
        if line is None:
            logger.warning(
                "%s: ORDER_IN dilewati — tidak ada OrderLine di %s (resource "
                "orders/order-lines belum terdaftar di Django?).",
                self.id,
                ", ".join(self.ORDER_LINE_PATHS),
            )
            return None

        order_line_id = line.get("id")
        if order_line_id in (None, ""):
            logger.warning("%s: ORDER_IN dilewati — OrderLine tanpa id.", self.id)
            return None
        # FASE 3.4 Fase 4: `_find_order_line` sudah menyaring, tapi dicek ulang —
        # WorkOrder tanpa produk membuat `GET /garmen/work-orders/<id>/` 500 dan
        # bundle-nya tak berguna, jadi JANGAN pernah POST di kasus itu.
        if not self._has_product(line):
            logger.warning(
                "%s: ORDER_IN dilewati — OrderLine %s tanpa product_code/product.",
                self.id,
                order_line_id,
            )
            return None
        qty = max(int(line.get("qty") or 0), 1)

        saved_timing = self.timing
        self.timing = None  # alur kritis: jangan idle/delay di antara 2 POST
        try:
            wo_response = await self._call(
                "POST /garmen/work-orders/",
                "POST",
                {"order_line_id": order_line_id},
                "scripted",
            )
            work_order_id = self._created_id(wo_response)
            if work_order_id is None:
                logger.warning(
                    "%s: WorkOrder tidak terbuat untuk order line %s (status %s).",
                    self.id,
                    order_line_id,
                    getattr(wo_response, "status_code", None),
                )
                return wo_response

            return await self._call(
                "POST /garmen/bundles/",
                "POST",
                {
                    "work_order_id": work_order_id,
                    "size_matrix": {"M": qty},
                    "bundle_size": self.DEFAULT_BUNDLE_SIZE,
                },
                "scripted",
            )
        finally:
            self.timing = saved_timing

    @staticmethod
    def _created_id(response) -> "Optional[int]":
        """Id objek dari respons **201** (``{"id": ...}``); ``None`` kalau bukan."""
        if response is None or getattr(response, "status_code", None) != 201:
            return None
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - respons tak terduga
            return None
        if isinstance(body, dict) and body.get("id") is not None:
            return int(body["id"])
        return None

    @classmethod
    def _has_product(cls, row: dict) -> bool:
        """True kalau OrderLine punya produk (``product_code`` ATAU ``product``)."""
        return any(row.get(key) for key in cls.PRODUCT_KEYS)

    async def _find_order_line(self) -> "Optional[dict]":
        """OrderLine **dengan produk** dari Django (terbaru lebih dulu).

        FASE 3.4 Fase 4: baris **tanpa produk** (`product_code`/`product` kosong)
        DILEWATI — WorkOrder untuk baris seperti itu akan membuat
        ``GET /garmen/work-orders/<id>/`` **500** (`serialize_work_order_detail`
        memanggil ``order_line.product.code``) dan bundle-nya tak bisa dipakai
        (rantai ``product_ref`` juga kosong). Baris berikutnya dicoba; kalau
        semua tanpa produk → ``None`` (event di-skip, bukan POST yang sia-sia).

        Dibaca lewat klien **langsung** (bukan ``_call``) supaya tidak terekam —
        alur ``ORDER_IN`` sengaja hanya merekam 2 POST (WorkOrder + Bundle).
        """

        for path in self.ORDER_LINE_PATHS:
            try:
                response = await self.client.get(path)
            except Exception:  # noqa: BLE001 - discovery tak boleh mematikan run
                continue
            if response.status_code != 200:
                continue
            rows = self._rows_of(response)
            skipped = 0
            for row in reversed(rows):  # terbaru lebih dulu
                if row.get("id") in (None, ""):
                    continue
                if not self._has_product(row):
                    skipped += 1
                    continue
                if skipped:
                    logger.info(
                        "%s: %d OrderLine tanpa produk dilewati; pakai OrderLine %s.",
                        self.id,
                        skipped,
                        row.get("id"),
                    )
                return row
            if rows:
                logger.warning(
                    "%s: %d OrderLine di %s semuanya tanpa product_code/product.",
                    self.id,
                    len(rows),
                    path,
                )
        return None

    @staticmethod
    def _rows_of(response) -> "list[dict]":
        """Baris dari respons list (``{"rows": [...]}`` atau array langsung)."""
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - respons tak terduga
            return []
        if isinstance(body, dict):
            body = body.get("rows") or []
        if not isinstance(body, list):
            return []
        return [row for row in body if isinstance(row, dict)]
