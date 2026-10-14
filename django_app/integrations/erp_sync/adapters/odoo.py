"""Adapter Odoo.

Isi modul ini:

* :class:`OdooJSONRPCAdapter` — transport JSON-RPC 2.0 ke Odoo 17
  (`POST {ODOO_URL}/jsonrpc`); dipakai untuk master data, ``OdooClient``, dan
  task diagnosa ``erp_sync.ping``.
* :class:`OdooAdapter` — adapter **two-stage sync** (WIP issue + FG receipt):
  memetakan payload agregat garmen ke ``stock.move`` Odoo memakai id lokasi dari
  settings (``ODOO_LOCATION_*``).
"""

from __future__ import annotations

import itertools
import logging
from typing import Any, Mapping, Sequence

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps_industry.garment.models import Order
from master.models import Product

from .base import STAGE_FG, STAGE_WIP, ERPAdapter, ERPResponse, ERPTransport

logger = logging.getLogger(__name__)

#: Stage scrap — alur ketiga (di luar two-stage WIP/FG). ``ERPResponse.stage`` string bebas.
STAGE_SCRAP = "SCRAP"
#: Stage invoice — alur keempat (Fase I5: piutang penjualan). String bebas.
STAGE_INVOICE = "INVOICE"
#: Stage inventory adjustment — alur kelima (H2.5). String bebas (sejajar label ledger).
STAGE_INVENTORY_ADJUST = "INVENTORY_ADJUST"

#: Stage stock transfer — alur keenam (H2.6): internal transfer via `stock.picking`.
STAGE_STOCK_TRANSFER = "STOCK_TRANSFER"

#: Stage vendor bill — alur ketujuh (H3.2): `account.move` **in_invoice** draft.
#: Terpisah dari `STAGE_INVOICE` (customer invoice/out_invoice, I5+H3.1) supaya
#: label monitor sync tidak ambigu; nilainya sejajar `STAGE_VENDOR_BILL` di
#: `integrations/erp_sync/models.py`.
STAGE_VENDOR_BILL = "VENDOR_BILL"

#: Stage payment — alur kedelapan (H3.3): `account.payment` **draft** (satu model dua
#: arah lewat `payment_type` `inbound`/`outbound`); sejajar `STAGE_PAYMENT` di
#: `integrations/erp_sync/models.py`.
STAGE_PAYMENT = "PAYMENT"

#: Stage journal entry manual — alur kesembilan (H3.4): `account.move`
#: ``move_type='entry'`` **draft** (double-entry manual dari MES); sejajar
#: `STAGE_JOURNAL_ENTRY` di `integrations/erp_sync/models.py`.
STAGE_JOURNAL_ENTRY = "JOURNAL_ENTRY"


#: Context Odoo untuk `stock.picking.button_validate()` H2.6: `skip_backorder=True`
#: melewati cabang wizard backorder (`stock_picking.py:1211`) sehingga pemanggilan
#: deterministik (transfer selalu penuh: `quantity` di-auto-isi = `product_uom_qty`).
TRANSFER_CTX = {"skip_backorder": True}

#: Context Odoo untuk jalur resmi inventory adjustment (`stock.quant` → apply).
#: `inventory_mode=True` = syarat field `inventory_quantity` bisa ditulis;
#: `set_inventory_quantity_auto_apply=True` = lewati wizard konflik/tracked Odoo
#: (flag internal yang dipakai `stock_change_product_qty` sendiri).
INVENTORY_CTX = {"inventory_mode": True, "set_inventory_quantity_auto_apply": True}


class OdooJSONRPCAdapter(ERPTransport):
    """Klien JSON-RPC ke Odoo.

    Struktur payload mengikuti server Odoo 17 (`odoo/service/common.py` &
    `odoo/service/model.py`):

    * service ``common``, method ``login``  → params ``[db, login, password]``
    * service ``object``, method ``execute_kw``
      → params ``[db, uid, password, model, method, args, kwargs]``

    Odoo 16+ menerima API key pada posisi ``password``, jadi ``api_key``
    dipakai sebagai pengganti password user.
    """

    name = "odoo-jsonrpc"

    def __init__(
        self,
        url: str,
        db: str,
        user: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        verify_ssl: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.user = user
        self.api_key = api_key
        self.timeout = timeout
        self.uid: int | None = None
        self._ids = itertools.count(1)
        self._client = client or httpx.Client(
            timeout=timeout,
            verify=verify_ssl,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    @property
    def endpoint(self) -> str:
        """URL endpoint JSON-RPC."""
        return f"{self.url}/jsonrpc"

    @staticmethod
    def _format_error(service: str, method: str, error: Any) -> str:
        """Rapikan payload error JSON-RPC Odoo jadi satu pesan."""
        name = None
        if isinstance(error, dict):
            data = error.get("data") or {}
            message = data.get("message") or error.get("message") or str(error)
            name = data.get("name") or error.get("code")
        else:  # pragma: no cover - format error tak terduga
            message = str(error)
        suffix = f" [{name}]" if name else ""
        return f"Odoo error saat {service}.{method}{suffix}: {message}"

    def _jsonrpc(self, service: str, method: str, args: Sequence) -> Any:
        """Kirim satu request JSON-RPC ke Odoo dan kembalikan `result`."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": list(args)},
            "id": next(self._ids),
        }
        try:
            response = self._client.post(self.endpoint, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Odoo JSON-RPC gagal ({service}.{method}) ke {self.endpoint}: {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Respons Odoo bukan JSON valid ({service}.{method}) dari {self.endpoint}."
            ) from exc

        if data.get("error"):
            raise RuntimeError(self._format_error(service, method, data["error"]))

        return data.get("result")

    def version(self) -> dict[str, Any]:
        """Info versi server Odoo (`common.version`) — tidak butuh autentikasi."""
        return dict(self._jsonrpc("common", "version", []) or {})

    def ping(self) -> bool:
        """Health check ringan: True kalau server Odoo menjawab `common.version`."""
        try:
            info = self.version()
        except Exception as exc:  # noqa: BLE001 - semua kegagalan = tidak sehat
            logger.warning("Odoo ping gagal ke %s: %s", self.endpoint, exc)
            return False
        logger.debug("Odoo ping ok (%s): %s", self.endpoint, info.get("server_version"))
        return bool(info)

    # ------------------------------------------------------------------
    # ERPTransport
    # ------------------------------------------------------------------
    def login(self) -> int:
        """Autentikasi via ``common.login``; fallback ke ``common.authenticate``."""
        uid = self._jsonrpc("common", "login", [self.db, self.user, self.api_key])
        if not uid:
            logger.debug("common.login gagal, mencoba common.authenticate ...")
            uid = self._jsonrpc(
                "common", "authenticate", [self.db, self.user, self.api_key, {}]
            )
        if not uid:
            raise RuntimeError(
                f"Login Odoo gagal (db={self.db!r}, user={self.user!r}); "
                "cek ODOO_DB/ODOO_USER/ODOO_API_KEY."
            )
        self.uid = int(uid)
        logger.info("Login Odoo sukses: db=%s user=%s uid=%s", self.db, self.user, self.uid)
        return self.uid

    def call(
        self,
        model: str,
        method: str,
        args: Sequence | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        """Wrapper ``object.execute_kw`` (login otomatis kalau belum ada uid)."""
        if self.uid is None:
            self.login()
        params = [
            self.db,
            self.uid,
            self.api_key,
            model,
            method,
            list(args or []),
            dict(kwargs or {}),
        ]
        return self._jsonrpc("object", "execute_kw", params)

    def search_read(
        self,
        model: str,
        domain: Sequence | None = None,
        fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Baca record dari Odoo (`model.search_read`)."""
        extra: dict[str, Any] = {}
        if fields:
            extra["fields"] = list(fields)
        if limit is not None:
            extra["limit"] = limit
        if offset:
            extra["offset"] = offset
        if order:
            extra["order"] = order
        result = self.call(model, "search_read", [list(domain or [])], extra)
        return list(result or [])

    def create(self, model: str, values: Mapping[str, Any]) -> int:
        """Buat record baru di Odoo (`model.create`)."""
        return int(self.call(model, "create", [dict(values)]))

    def write(self, model: str, ids: Sequence[int], values: Mapping[str, Any]) -> bool:
        """Update record di Odoo (`model.write`)."""
        return bool(self.call(model, "write", [list(ids), dict(values)]))

    # ------------------------------------------------------------------
    # resource
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Tutup koneksi HTTP client."""
        self._client.close()

    def __enter__(self) -> "OdooJSONRPCAdapter":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"<OdooJSONRPCAdapter url={self.url} db={self.db} "
            f"user={self.user} uid={self.uid}>"
        )


class OdooAdapter(ERPAdapter):
    """Adapter two-stage sync ke Odoo (WIP issue + FG receipt) — Fase 4.2.

    Alur setiap ``push_*``:

      1. validasi payload (wajib: ``product_ref``, ``qty``, ``ref``);
      2. cari ``master.Product`` lewat ``code`` lalu pakai ``odoo_id``-nya;
      3. validasi id lokasi Odoo dari settings (``ODOO_LOCATION_*``);
      4. ``client.execute_kw("stock.move", "create", [[...]])`` — Odoo tetap
         "passive notary": Django yang memutuskan, Odoo yang mencatat move;
      5. kembalikan :class:`ERPResponse` (``erp_id`` = id ``stock.move``).

    Semua kegagalan (payload kurang, product/lokasi belum siap, error JSON-RPC)
    dikembalikan sebagai ``ERPResponse(ok=False, ...)`` — **bukan** exception —
    supaya task Celery mencatatnya ke ``SyncRecord`` (attempts + error) tanpa
    membatalkan alur produksi di lantai.
    """

    name = "odoo"

    def __init__(self, client: Any | None = None) -> None:
        """``client`` opsional (untuk test); kalau None dibangun dari settings.

        Import ``get_odoo_rpc_client`` sengaja di dalam method karena
        ``client.py`` mengimpor modul ini (kalau di level modul -> melingkar).
        """
        self.client: Any | None = client
        if client is None:
            from ..client import get_odoo_rpc_client

            try:
                self.client = get_odoo_rpc_client()
            except ImproperlyConfigured as exc:
                logger.warning("OdooAdapter: kredensial Odoo belum lengkap -> %s", exc)
                self.client = None
        self.location_wip_id = getattr(settings, "ODOO_LOCATION_WIP_ID", None)
        self.location_production_id = getattr(settings, "ODOO_LOCATION_PRODUCTION_ID", None)
        self.location_fg_id = getattr(settings, "ODOO_LOCATION_FG_ID", None)
        self.location_scrap_id = getattr(settings, "ODOO_LOCATION_SCRAP_ID", None)
        # H2.6 — tipe picking internal transfer: dari settings bila ada, kalau tidak
        # dicari `stock.picking.type` code='internal' saat push (TANPA hardcode id).
        self.internal_picking_type_id = getattr(settings, "ODOO_PICKING_TYPE_INTERNAL_ID", None)

    # ------------------------------------------------------------------ push
    def push_wip_issue(self, payload: dict) -> ERPResponse:
        """WIP issue: bahan keluar dari gudang bahan -> lokasi produksi."""
        return self._push(
            payload,
            stage=STAGE_WIP,
            source_location=self.location_wip_id,
            dest_location=self.location_production_id,
            location_label="WIP/PRODUCTION",
        )

    def push_fg_receipt(self, payload: dict) -> ERPResponse:
        """FG receipt: barang jadi masuk dari lokasi produksi -> gudang FG."""
        return self._push(
            payload,
            stage=STAGE_FG,
            source_location=self.location_production_id,
            dest_location=self.location_fg_id,
            location_label="PRODUCTION/FG",
        )

    # ------------------------------------------------------- WO (Step 7)
    def push_wip_issue_wo(self, wo: dict) -> ERPResponse:
        """WIP issue dari dict WorkOrder (Step 7) — **tanpa** mengubah `push_wip_issue`.

        ``wo`` minimal: ``{"product_id": <pk Product Django>, "qty": <float>,
        "ref": <str>}`` (+ opsional ``"uom_id"`` = id ``uom.uom`` Odoo).

        * **Mapping produk**: ``master.Product.id`` → ``Product.odoo_id`` (Odoo).
        * **Idempotency**: sengaja **TIDAK** di sini — ditangani ``tasks``
          (``SyncRecord`` / ``SyncIdempotency``).
        * **Lokasi**: dari settings ``ODOO_LOCATION_WIP_ID`` (sumber) dan
          ``ODOO_LOCATION_PRODUCTION_ID`` (tujuan) — tidak ada id hardcode.
        * Return ``ERPResponse`` (``erp_id`` = id ``stock.move``); semua gagal
          → ``ok=False`` (tidak melempar exception).
        """
        data = dict(wo or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("product_id", "qty", "ref") if not data.get(name)]
        if missing:
            return self._error(
                f"WO tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_WIP,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_WIP,
                ref=ref,
            )
        if not self.location_wip_id or not self.location_production_id:
            return self._error(
                "Location WIP/PRODUCTION belum dikonfigurasi (ODOO_LOCATION_*).",
                stage=STAGE_WIP,
                ref=ref,
            )

        product = Product.objects.filter(pk=data["product_id"]).first()
        if product is None:
            return self._error(
                f"Product tidak ditemukan: {data['product_id']}.", stage=STAGE_WIP, ref=ref
            )
        if not product.odoo_id:
            return self._error(
                f"Product {data['product_id']} belum punya odoo_id (sync master dulu).",
                stage=STAGE_WIP,
                ref=ref,
            )

        try:
            qty = float(data["qty"])
        except (TypeError, ValueError):
            return self._error(f"Qty tidak valid: {data['qty']!r}.", stage=STAGE_WIP, ref=ref)

        values: dict[str, Any] = {
            "product_id": int(product.odoo_id),
            "product_uom_qty": qty,
            "location_id": int(self.location_wip_id),
            "location_dest_id": int(self.location_production_id),
            "reference": ref,
            "name": ref,
        }
        uom_id = data.get("uom_id")
        if uom_id:
            values["product_uom"] = int(uom_id)

        try:
            result = self.client.execute_kw("stock.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_WIP, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error("Odoo tidak mengembalikan id stock.move.", stage=STAGE_WIP, ref=ref)

        logger.info("OdooAdapter: WIP-WO %s -> stock.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_WIP,
            ref=ref,
        )

    # ------------------------------------------------------- WO (Step 8)
    def push_fg_receipt_wo(self, wo: dict) -> ERPResponse:
        """FG receipt dari dict WorkOrder (Step 8) — **tanpa** mengubah `push_fg_receipt`.

        ``wo`` minimal: ``{"product_id": <pk Product Django>, "qty": <float>,
        "ref": <str>}`` (+ opsional ``"uom_id"`` = id ``uom.uom`` Odoo).

        * **Mapping produk**: ``master.Product.id`` → ``Product.odoo_id`` (Odoo).
        * **Idempotency**: sengaja **TIDAK** di sini — ditangani ``tasks``
          (``SyncRecord`` / ``SyncIdempotency``, stage ``FG``).
        * **Lokasi**: dari settings ``ODOO_LOCATION_PRODUCTION_ID`` (sumber) dan
          ``ODOO_LOCATION_FG_ID`` (tujuan) — tidak ada id hardcode.
        * Return ``ERPResponse`` (``erp_id`` = id ``stock.move``); semua gagal
          → ``ok=False`` (tidak melempar exception).
        """
        data = dict(wo or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("product_id", "qty", "ref") if not data.get(name)]
        if missing:
            return self._error(
                f"WO tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_FG,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_FG,
                ref=ref,
            )
        if not self.location_production_id or not self.location_fg_id:
            return self._error(
                "Location PRODUCTION/FG belum dikonfigurasi (ODOO_LOCATION_*).",
                stage=STAGE_FG,
                ref=ref,
            )

        product = Product.objects.filter(pk=data["product_id"]).first()
        if product is None:
            return self._error(
                f"Product tidak ditemukan: {data['product_id']}.", stage=STAGE_FG, ref=ref
            )
        if not product.odoo_id:
            return self._error(
                f"Product {data['product_id']} belum punya odoo_id (sync master dulu).",
                stage=STAGE_FG,
                ref=ref,
            )

        try:
            qty = float(data["qty"])
        except (TypeError, ValueError):
            return self._error(f"Qty tidak valid: {data['qty']!r}.", stage=STAGE_FG, ref=ref)

        values: dict[str, Any] = {
            "product_id": int(product.odoo_id),
            "product_uom_qty": qty,
            "location_id": int(self.location_production_id),
            "location_dest_id": int(self.location_fg_id),
            "reference": ref,
            "name": ref,
        }
        uom_id = data.get("uom_id")
        if uom_id:
            values["product_uom"] = int(uom_id)

        try:
            result = self.client.execute_kw("stock.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_FG, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error("Odoo tidak mengembalikan id stock.move.", stage=STAGE_FG, ref=ref)

        logger.info("OdooAdapter: FG-WO %s -> stock.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_FG,
            ref=ref,
        )

    # --------------------------------------------------- WO (Step 9: SCRAP)
    def push_scrap_wo(self, wo: dict) -> ERPResponse:
        """Scrap (barang rusak/afval) dari dict WorkOrder (Step 9).

        Model Odoo = **``stock.scrap``** — BUKAN ``stock.move.line`` + ``is_scrap``
        (field itu **tidak ada** di build ini; sudah diverifikasi:
        ``ValueError: Invalid field 'is_scrap' on model 'stock.move.line'``).

        ``wo`` minimal: ``{"product_id": <pk Product Django>, "qty": <float>,
        "ref": <str>, "uom_id": <id uom.uom Odoo>}`` — ``uom_id`` **wajib**
        (``stock.scrap.product_uom_id`` required).

        * **Mapping produk**: ``master.Product.id`` → ``Product.odoo_id`` (Odoo).
        * **Idempotency**: sengaja **TIDAK** di sini — ditangani ``tasks``.
        * **Lokasi**: ``ODOO_LOCATION_WIP_ID`` (asal) & ``ODOO_LOCATION_SCRAP_ID``
          (lokasi scrap) dari settings — tidak ada id hardcode.
        * Setelah ``create`` → panggil Odoo ``action_validate`` (state → ``done``).
          Kalau tidak jadi ``done`` (mis. stok kurang → Odoo balas wizard), draft
          di-``unlink`` lagi (best-effort) supaya tak ada record menggantung.
        * Return ``ERPResponse`` (``erp_id`` = id ``stock.scrap``); gagal → ``ok=False``.
        """
        data = dict(wo or {})
        ref = str(data.get("ref") or "")
        missing = [n for n in ("product_id", "qty", "ref", "uom_id") if not data.get(n)]
        if missing:
            return self._error(
                f"WO tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_SCRAP,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_SCRAP,
                ref=ref,
            )
        if not self.location_wip_id or not self.location_scrap_id:
            return self._error(
                "Location WIP/SCRAP belum dikonfigurasi (ODOO_LOCATION_*).",
                stage=STAGE_SCRAP,
                ref=ref,
            )

        product = Product.objects.filter(pk=data["product_id"]).first()
        if product is None:
            return self._error(
                f"Product tidak ditemukan: {data['product_id']}.", stage=STAGE_SCRAP, ref=ref
            )
        if not product.odoo_id:
            return self._error(
                f"Product {data['product_id']} belum punya odoo_id (sync master dulu).",
                stage=STAGE_SCRAP,
                ref=ref,
            )

        try:
            qty = float(data["qty"])
        except (TypeError, ValueError):
            return self._error(f"Qty tidak valid: {data['qty']!r}.", stage=STAGE_SCRAP, ref=ref)

        values: dict[str, Any] = {
            "product_id": int(product.odoo_id),
            "scrap_qty": qty,
            "product_uom_id": int(data["uom_id"]),
            "location_id": int(self.location_wip_id),
            "scrap_location_id": int(self.location_scrap_id),
            "name": ref,
            "origin": ref,
        }
        try:
            result = self.client.execute_kw("stock.scrap", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_SCRAP, ref=ref)

        scrap_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if scrap_id is None:
            return self._error("Odoo tidak mengembalikan id stock.scrap.", stage=STAGE_SCRAP, ref=ref)

        # Validasi (draft -> done) supaya barang rusak langsung tercatat keluar.
        try:
            self.client.execute_kw("stock.scrap", "action_validate", [[scrap_id]])
            records = self.client.execute_kw("stock.scrap", "read", [[scrap_id], ["state"]])
            state = records[0].get("state") if records else None
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            self._discard_scrap(scrap_id)
            return self._error(str(exc), stage=STAGE_SCRAP, ref=ref)

        if state != "done":
            # Odoo tidak memvalidasi (mis. stok kurang -> balas wizard) -> buang draft.
            self._discard_scrap(scrap_id)
            return self._error(
                f"stock.scrap {scrap_id} tidak tervalidasi (state={state}).",
                stage=STAGE_SCRAP,
                ref=ref,
            )

        logger.info("OdooAdapter: SCRAP-WO %s -> stock.scrap %s", ref, scrap_id)
        return ERPResponse(
            ok=True,
            erp_id=str(scrap_id),
            raw={"scrap_id": scrap_id, "values": values, "state": state},
            error=None,
            stage=STAGE_SCRAP,
            ref=ref,
        )

    # ------------------------------------------------- customer invoice (I5)
    def push_customer_invoice_wo(self, wo: dict) -> ERPResponse:
        """Buat **customer invoice** (``account.move``) dari dict Order (Fase I5).

        ``wo`` minimal: ``{"order_id": <pk Order Django>, "ref": <str>}``
        (+ opsional ``"invoice_date"`` berformat ``"YYYY-MM-DD"``).

        * **Mapping** mengikuti ``push_scrap_wo``: ``wo`` mengirim **pk Django**,
          adapter yang menerjemahkan → ``Order.customer`` → ``Partner.odoo_id``
          dan ``OrderLine.product`` → ``Product.odoo_id`` (varian).
        * ``move_type="out_invoice"``; ``price_unit`` sementara ``0`` (MES belum
          menyimpan harga) → supervisor melengkapi di UI Odoo.
        * ``journal_id`` / ``currency_id`` **tidak** dikirim → Odoo memakai
          default company.
        * ``action_post`` **tidak** dipanggil: invoice dibiarkan **draft**.
        * **Idempotency**: sengaja **TIDAK** di sini — ditangani ``SyncRecord``
          (``resource="order"``, ``stage="INVOICE"``) di service/task.
        * Semua kegagalan (termasuk customer/produk tanpa ``odoo_id``) →
          ``ERPResponse(ok=False)`` — **tidak** melempar exception.
        """
        data = dict(wo or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("order_id", "ref") if not data.get(name)]
        if missing:
            return self._error(
                f"WO tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_INVOICE,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        order = Order.objects.filter(pk=data["order_id"]).first()
        if order is None:
            return self._error(
                f"Order tidak ditemukan: {data['order_id']}.",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        partner = order.customer
        if partner is None or not partner.odoo_id:
            return self._error(
                f"Order {order.code} belum punya customer dengan odoo_id "
                "(sync master partner dulu).",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        invoice_lines = self._invoice_lines(order)
        if not invoice_lines:
            return self._error(
                f"Order {order.code} tidak punya OrderLine dengan product.odoo_id.",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        values: dict[str, Any] = {
            "partner_id": int(partner.odoo_id),
            "move_type": "out_invoice",
            "invoice_date": str(data.get("invoice_date") or timezone.localdate()),
            "ref": ref,
            "invoice_line_ids": invoice_lines,
        }
        try:
            result = self.client.execute_kw("account.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_INVOICE, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error(
                "Odoo tidak mengembalikan id account.move.",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        logger.info("OdooAdapter: INVOICE-WO %s -> account.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_INVOICE,
            ref=ref,
        )

    @staticmethod
    def _invoice_lines(order) -> list[tuple]:
        """Baris invoice (command Odoo ``(0, 0, {...})``) dari OrderLine order.

        OrderLine yang produknya **belum** punya ``odoo_id`` dilewati (tidak
        menggagalkan seluruh invoice); kalau semua terlewat, pemanggil
        mengembalikan ``ok=False``.
        """
        lines: list[tuple] = []
        for order_line in order.lines.select_related("product").order_by("id"):
            product = order_line.product
            if product is None or not product.odoo_id:
                continue
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": int(product.odoo_id),
                        "quantity": order_line.qty,
                        "price_unit": 0,
                        "name": product.code,
                    },
                )
            )
        return lines

    def push_inventory_adjustment(self, payload: dict) -> ERPResponse:
        """Inventory adjustment (H2.5) lewat jalur **resmi** Odoo 17.

        Dipilih dari probe STEP 0 + sumber Odoo (`stock/models/stock_quant.py`,
        `stock/wizard/stock_change_product_qty.py`):

        * **BUKAN** ``stock.move`` + ``_action_done()``: ``_action_done`` adalah
          method *private* ⇒ tidak dapat dipanggil via XML-RPC;
        * **BUKAN** ``stock.inventory.adjustment``: model itu **tidak ada** di Odoo 17
          (yang ada wizard ``stock.inventory.adjustment.name`` — hanya pengisi nama);
        * **YA** ``stock.quant``: baca ``quantity`` (on-hand) → tulis
          ``inventory_quantity`` = on-hand + delta (context ``inventory_mode=True``)
          → ``action_apply_inventory()`` (PUBLIK). Odoo sendiri yang membuat
          ``stock.move`` (dari/ke ``property_stock_inventory``) + ``_action_done()``,
          dengan nama move = context ``inventory_name`` ⇒ bisa ditelusuri.

        ``payload`` minimal: ``{"ref", "product_odoo_id", "location_odoo_id",
        "qty_delta", "inventory_name"}``. Return ``ERPResponse`` (``erp_id`` = id
        ``stock.move``; ``raw`` = ``{"quant_id", "before", "target", "move_id"}``).

        ⚠️ Prasyarat: user API Odoo harus punya ``stock.group_stock_manager`` —
        tanpa itu ``action_apply_inventory`` → ``UserError`` (diteruskan apa adanya
        supaya terlihat di UI/task).
        """
        data = dict(payload or {})
        ref = str(data.get("ref") or "")
        missing = [
            name
            for name in ("product_odoo_id", "location_odoo_id", "qty_delta", "inventory_name")
            if data.get(name) in (None, "")
        ]
        if missing:
            return self._error(
                f"Payload adjustment tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_INVENTORY_ADJUST,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_INVENTORY_ADJUST,
                ref=ref,
            )

        try:
            product_id = int(data["product_odoo_id"])
            location_id = int(data["location_odoo_id"])
            delta = float(data["qty_delta"])
        except (TypeError, ValueError):
            return self._error(
                "Payload adjustment tidak valid (product/location/qty_delta harus angka).",
                stage=STAGE_INVENTORY_ADJUST,
                ref=ref,
            )

        inventory_name = str(data["inventory_name"])[:64]
        ctx = {**INVENTORY_CTX, "inventory_name": inventory_name}

        try:
            # 1) on-hand terkini (dibaca *fresh* tepat sebelum apply: MES menyimpan
            #    delta, sedangkan Odoo menuntut nilai absolut).
            quants = self.client.execute_kw(
                "stock.quant",
                "search_read",
                [[["product_id", "=", product_id], ["location_id", "=", location_id]]],
                {"fields": ["id", "quantity"], "limit": 1, "context": ctx},
            )
            if quants:
                quant_id = quants[0].get("id")
                before = float(quants[0].get("quantity") or 0.0)
            else:
                quant_id = None
                before = 0.0
            target = before + delta

            # 2) tulis target absolut ke `inventory_quantity` (butuh `inventory_mode`).
            values = {
                "product_id": product_id,
                "location_id": location_id,
                "inventory_quantity": target,
            }
            if quant_id:
                self.client.execute_kw("stock.quant", "write", [[quant_id], values], {"context": ctx})
            else:
                created = self.client.execute_kw("stock.quant", "create", [values], {"context": ctx})
                quant_id = created[0] if isinstance(created, (list, tuple)) and created else created

            # 3) apply — Odoo membuat stock.move + `_action_done()` sendiri.
            self.client.execute_kw(
                "stock.quant", "action_apply_inventory", [[quant_id]], {"context": ctx}
            )

            # 4) jejak move adjustment (name/reference = `inventory_name`).
            move_id = None
            moves = self.client.execute_kw(
                "stock.move",
                "search_read",
                [[["location_id.usage", "in", ["inventory", "internal"]]]],
                {
                    "fields": ["id", "name"],
                    "limit": 5,
                    "order": "id desc",
                    "context": ctx,
                },
            )
            for row in moves or []:
                if str(row.get("name") or "") == inventory_name:
                    move_id = row.get("id")
                    break
        except Exception as exc:  # noqa: BLE001 - semua error Odoo -> ok=False
            return self._error(str(exc), stage=STAGE_INVENTORY_ADJUST, ref=ref)

        logger.info(
            "OdooAdapter: INVENTORY_ADJUST %s product=%s loc=%s %s->%s (quant %s, move %s).",
            ref,
            product_id,
            location_id,
            before,
            target,
            quant_id,
            move_id,
        )
        return ERPResponse(
            ok=True,
            erp_id=str(move_id) if move_id else str(quant_id),
            raw={"quant_id": quant_id, "before": before, "target": target, "move_id": move_id},
            error=None,
            stage=STAGE_INVENTORY_ADJUST,
            ref=ref,
        )

    def push_stock_transfer_wo(self, transfer: dict) -> ERPResponse:
        """Stock Transfer internal (H2.6) lewat jalur **resmi** Odoo 17: ``stock.picking``.

        Dipilih dari probe STEP 0 + sumber `stock/models/stock_picking.py`:

        * ``stock.move`` + ``_action_done()`` **tidak bisa** via RPC (`_action_done`
          private, `stock_picking.py:978`);
        * **``button_validate()`` (PUBLIK, 1134)** melakukan seluruh rangkaian:
          `draft_picking.action_confirm()` (1137) → auto-isi ``move.quantity =
          product_uom_qty`` (1138–1141) → `_pre_action_done_hook()` auto-set
          ``picked=True`` (1206–1210) → `_action_done()` (1163);
        * ``skip_backorder=True`` menonaktifkan cabang wizard backorder (1211) supaya
          pemanggilan RPC deterministik; hasilnya tetap diperiksa (``state == 'done'``).

        ``transfer`` minimal: ``{"ref", "product_odoo_id", "from_location_odoo_id",
        "to_location_odoo_id", "qty", "move_name", "origin"}``. Tipe picking internal
        diambil dari settings ``ODOO_PICKING_TYPE_INTERNAL_ID`` bila ada, kalau tidak
        dicari **berdasarkan ``code='internal'``** (tanpa hardcode id).
        Return ``ERPResponse`` (``erp_id`` = id ``stock.picking``).
        """
        data = dict(transfer or {})
        ref = str(data.get("ref") or "")
        missing = [
            name
            for name in (
                "ref",
                "product_odoo_id",
                "from_location_odoo_id",
                "to_location_odoo_id",
                "qty",
            )
            if data.get(name) in (None, "")
        ]
        if missing:
            return self._error(
                f"Payload transfer tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_STOCK_TRANSFER,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_STOCK_TRANSFER,
                ref=ref,
            )

        try:
            product_id = int(data["product_odoo_id"])
            from_location_id = int(data["from_location_odoo_id"])
            to_location_id = int(data["to_location_odoo_id"])
            qty = float(data["qty"])
        except (TypeError, ValueError):
            return self._error(
                "Payload transfer tidak valid (product/lokasi/qty harus angka).",
                stage=STAGE_STOCK_TRANSFER,
                ref=ref,
            )

        if qty <= 0:
            return self._error(
                f"Qty transfer harus > 0 (dapat {qty}).", stage=STAGE_STOCK_TRANSFER, ref=ref
            )
        if from_location_id == to_location_id:
            return self._error(
                "Lokasi asal & tujuan sama — transfer tidak bermakna.",
                stage=STAGE_STOCK_TRANSFER,
                ref=ref,
            )

        try:
            picking_type_id = self._internal_picking_type_id()
        except Exception as exc:  # noqa: BLE001 - pembacaan tipe picking gagal
            return self._error(str(exc), stage=STAGE_STOCK_TRANSFER, ref=ref)

        if not picking_type_id:
            return self._error(
                "Tipe picking internal transfer tidak ditemukan di Odoo "
                "(set ODOO_PICKING_TYPE_INTERNAL_ID atau pastikan ada stock.picking.type "
                "dengan code='internal').",
                stage=STAGE_STOCK_TRANSFER,
                ref=ref,
            )

        move_name = str(data.get("move_name") or ref)[:64]
        values: dict[str, Any] = {
            "picking_type_id": int(picking_type_id),
            "location_id": from_location_id,
            "location_dest_id": to_location_id,
            "origin": str(data.get("origin") or ref)[:64],
            "move_ids": [
                (
                    0,
                    0,
                    {
                        "name": move_name,
                        "product_id": product_id,
                        "product_uom_qty": qty,
                        "location_id": from_location_id,
                        "location_dest_id": to_location_id,
                    },
                )
            ],
        }
        return self._validate_transfer_picking(values, ref=ref, stage=STAGE_STOCK_TRANSFER)

    def _validate_transfer_picking(self, values: dict, *, ref: str, stage: str) -> ERPResponse:
        """Create ``stock.picking`` → ``button_validate()`` → verifikasi ``state == 'done'``.

        `button_validate()` (publik) sudah mencakup `action_confirm` + auto-isi
        `quantity` + auto-`picked` + `_action_done`, jadi MES **tidak** memanggil
        `action_assign()` manual (2 langkah & risiko state, sesuai keputusan H2.6).
        """
        try:
            result = self.client.execute_kw("stock.picking", "create", [[values]])
            picking_id = result[0] if isinstance(result, (list, tuple)) and result else result
            if picking_id is None:
                return self._error(
                    "Odoo tidak mengembalikan id stock.picking.", stage=stage, ref=ref
                )

            validated = self.client.execute_kw(
                "stock.picking", "button_validate", [[picking_id]], {"context": dict(TRANSFER_CTX)}
            )
            if isinstance(validated, dict):
                return self._error(
                    "Odoo meminta konfirmasi tambahan (wizard) saat validasi transfer — "
                    "transfer TIDAK selesai; periksa picking di Odoo.",
                    stage=stage,
                    ref=ref,
                )

            rows = self.client.execute_kw(
                "stock.picking",
                "search_read",
                [[["id", "=", picking_id]]],
                {"fields": ["name", "state"], "limit": 1},
            )
        except Exception as exc:  # noqa: BLE001 - semua error Odoo (mis. stok kurang) -> ok=False
            return self._error(str(exc), stage=stage, ref=ref)

        row = rows[0] if rows else {}
        picking_name = str(row.get("name") or "")
        state = str(row.get("state") or "")
        if state != "done":
            return self._error(
                f"Picking {picking_name or picking_id} berstatus '{state}' (bukan 'done') — "
                "transfer tidak selesai di Odoo.",
                stage=stage,
                ref=ref,
            )

        logger.info(
            "OdooAdapter: %s %s -> stock.picking %s (%s) validated.", stage, ref, picking_name, state
        )
        return ERPResponse(
            ok=True,
            erp_id=str(picking_id),
            raw={
                "picking_id": picking_id,
                "picking_name": picking_name,
                "state": state,
                "values": values,
            },
            error=None,
            stage=stage,
            ref=ref,
        )

    def _internal_picking_type_id(self):
        """ID tipe picking internal: settings dulu, lalu cari ``code='internal'``.

        TIDAK ada id hardcode: nilai settings (``ODOO_PICKING_TYPE_INTERNAL_ID``)
        dihormati; kalau kosong dicari lewat Odoo (read-only) dan di-cache selama
        adapter hidup.
        """
        if self.internal_picking_type_id:
            return int(self.internal_picking_type_id)

        rows = (
            self.client.execute_kw(
                "stock.picking.type",
                "search_read",
                [[["code", "=", "internal"]]],
                {"fields": ["name", "code"], "limit": 1},
            )
            if self.client is not None
            else []
        )
        if not rows:
            return None

        self.internal_picking_type_id = rows[0].get("id")

        return self.internal_picking_type_id

    def _discard_scrap(self, scrap_id: int) -> None:
        """Best-effort hapus draft ``stock.scrap`` (biar tidak ada record menggantung)."""
        try:
            self.client.execute_kw("stock.scrap", "unlink", [[scrap_id]])
        except Exception as exc:  # noqa: BLE001 - cleanup best-effort
            logger.warning(
                "OdooAdapter: gagal bersihkan draft stock.scrap %s: %s", scrap_id, exc
            )

    # -------------------------------------------------------------- internal
    def _push(
        self,
        payload: dict,
        *,
        stage: str,
        source_location: int | None,
        dest_location: int | None,
        location_label: str,
    ) -> ERPResponse:
        """Bangun & kirim satu ``stock.move``; semua kegagalan -> ``ok=False``."""
        data = dict(payload or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("product_ref", "qty", "ref") if not data.get(name)]
        if missing:
            return self._error(
                f"Payload tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=stage,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=stage,
                ref=ref,
            )
        if not source_location or not dest_location:
            return self._error(
                f"Location {location_label} belum dikonfigurasi (ODOO_LOCATION_*).",
                stage=stage,
                ref=ref,
            )

        product_ref = str(data["product_ref"])
        product = Product.objects.filter(code=product_ref).first()
        if product is None:
            return self._error(
                f"Product tidak ditemukan: {product_ref}.", stage=stage, ref=ref
            )
        if not product.odoo_id:
            return self._error(
                f"Product {product_ref} belum punya odoo_id (sync master dulu).",
                stage=stage,
                ref=ref,
            )

        try:
            qty = float(data["qty"])
        except (TypeError, ValueError):
            return self._error(f"Qty tidak valid: {data['qty']!r}.", stage=stage, ref=ref)

        values: dict[str, Any] = {
            "product_id": int(product.odoo_id),
            "product_uom_qty": qty,
            "location_id": int(source_location),
            "location_dest_id": int(dest_location),
            "reference": ref,
            "name": ref,
        }
        try:
            result = self.client.execute_kw("stock.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=stage, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error("Odoo tidak mengembalikan id stock.move.", stage=stage, ref=ref)

        logger.info("OdooAdapter: %s %s -> stock.move %s", stage, ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=stage,
            ref=ref,
        )

    # ------------------------------------------- customer invoice MES (H3.1)
    def push_customer_invoice(self, payload: dict) -> ERPResponse:
        """Buat **customer invoice** (``account.move``) dari payload **eksplisit**.

        Berbeda dari :meth:`push_customer_invoice_wo` (I5 — membaca ``Order`` dan
        mengirim ``price_unit=0`` tanpa pajak), method ini menerima baris yang sudah
        dihitung MES (harga & pajak nyata dari model ``CustomerInvoice``):

        ``payload`` minimal::

            {
              "ref": "INV-2026-0001",
              "partner_odoo_id": 10,
              "invoice_date": "2026-10-12",
              "due_date": "2026-11-12",            # opsional
              "lines": [
                {"product_odoo_id": 34, "quantity": 5, "price_unit": 4000,
                 "name": "[FURN_6741] ...",        # opsional (default: ref)
                 "tax_odoo_ids": [19]},            # opsional
              ],
            }

        Aturan (probe STEP 0 + sumber Odoo 17):

        * ``move_type="out_invoice"`` **wajib** dikirim eksplisit — ``default_get``
          Odoo menjawab ``move_type='entry'`` kalau tidak;
        * baris memakai command One2many ``(0, 0, {...})``; pajak dikirim sebagai
          **m2m command** ``tax_ids: [(6, 0, [id…])]``;
        * ``account_id``/``product_uom_id``/``name`` **tidak** dikirim — Odoo
          mengisinya otomatis dari ``product_id`` (terbukti pada sample dev);
        * ``journal_id``/``currency_id`` tidak dikirim (default company);
        * ``action_post`` **tidak** dipanggil → invoice dibiarkan **draft** supaya
          akuntan memeriksa & mem-posting di UI Odoo;
        * semua kegagalan (payload tidak lengkap / error Odoo) → ``ERPResponse(ok=False)``
          — **tidak** melempar exception (pola ``push_scrap_wo``).
        """
        data = dict(payload or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("ref", "partner_odoo_id", "lines") if not data.get(name)]
        if missing:
            return self._error(
                f"Payload invoice tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_INVOICE,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        try:
            partner_id = int(data["partner_odoo_id"])
        except (TypeError, ValueError):
            return self._error(
                f"partner_odoo_id tidak valid: {data['partner_odoo_id']!r}.",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        lines: list[tuple] = []
        for raw_line in data["lines"] or []:
            line = dict(raw_line or {})
            if not line.get("product_odoo_id"):
                return self._error(
                    "Setiap baris invoice wajib punya product_odoo_id (sync produk dulu).",
                    stage=STAGE_INVOICE,
                    ref=ref,
                )
            try:
                quantity = float(line.get("quantity") or 0)
                price_unit = float(line.get("price_unit") or 0)
            except (TypeError, ValueError):
                return self._error(
                    "quantity/price_unit baris invoice harus berupa angka.",
                    stage=STAGE_INVOICE,
                    ref=ref,
                )
            if quantity <= 0:
                return self._error(
                    "quantity baris invoice harus > 0 (Odoo menolak 0).",
                    stage=STAGE_INVOICE,
                    ref=ref,
                )

            line_values: dict[str, Any] = {
                "product_id": int(line["product_odoo_id"]),
                "quantity": quantity,
                "price_unit": price_unit,
                "name": str(line.get("name") or ref),
            }
            tax_ids = [int(tax) for tax in (line.get("tax_odoo_ids") or []) if tax]
            if tax_ids:
                # m2m di dalam command One2many: set id pajak (mengganti isi).
                line_values["tax_ids"] = [(6, 0, tax_ids)]

            lines.append((0, 0, line_values))

        if not lines:
            return self._error(
                "Invoice tidak punya baris yang bisa dikirim (semua produk tanpa odoo_id).",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        values: dict[str, Any] = {
            "partner_id": partner_id,
            "move_type": "out_invoice",
            "invoice_date": str(data.get("invoice_date") or timezone.localdate()),
            "ref": ref,
            "invoice_line_ids": lines,
        }
        due_date = data.get("due_date")
        if due_date:
            values["invoice_date_due"] = str(due_date)

        try:
            result = self.client.execute_kw("account.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_INVOICE, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error(
                "Odoo tidak mengembalikan id account.move.",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        logger.info("OdooAdapter: CUSTOMER_INVOICE %s -> account.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_INVOICE,
            ref=ref,
        )

    def cancel_customer_invoice(self, erp_id) -> ERPResponse:
        """Batalkan customer invoice di Odoo (``account.move.button_cancel``) — H3.1.

        Dipakai saat invoice MES dibatalkan **setelah** pernah terkirim
        (`odoo_id` ada). Odoo menolak dengan pesan jelas kalau move sudah
        diposting/pindah state (diteruskan apa adanya sebagai ``ok=False``);
        pembatalan di MES tetap sah (pola ``cancel_purchase_order`` H2.2).
        """
        ref = str(erp_id or "")
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_INVOICE,
                ref=ref,
            )

        try:
            move_id = int(erp_id)
        except (TypeError, ValueError):
            return self._error(f"erp_id invoice tidak valid: {erp_id!r}.", stage=STAGE_INVOICE, ref=ref)

        try:
            self.client.execute_kw("account.move", "button_cancel", [[move_id]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_INVOICE, ref=ref)

        logger.info("OdooAdapter: CUSTOMER_INVOICE cancel %s -> button_cancel", move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"cancelled": move_id},
            error=None,
            stage=STAGE_INVOICE,
            ref=ref,
        )

    # ------------------------------------------- vendor bill MES (H3.2)
    def push_vendor_bill(self, payload: dict) -> ERPResponse:
        """Buat **vendor bill** Odoo (`account.move` `in_invoice`, **draft**).

        ``payload`` minimal::

            {
              "ref": "INV-VENDOR-001",          # best-effort (fallback kode MES VB-…)
              "partner_odoo_id": 14,            # vendor
              "invoice_date": "2026-10-13",
              "due_date": "2026-11-13",         # opsional
              "lines": [
                {"product_odoo_id": 34, "quantity": 10, "price_unit": 1500,
                 "name": "...",                 # opsional (default: ref)
                 "tax_odoo_ids": [20]},         # opsional
              ],
            }

        Aturan (probe STEP 0 H3.2 + sumber Odoo 17):

        * ``move_type="in_invoice"`` **wajib dikirim eksplisit** — ``default_get``
          Odoo menjawab ``move_type='entry'`` kalau tidak (sama seperti H3.1);
        * ``ref`` **tidak wajib** di Odoo (`required=False`, tanpa `required="1"`
          di view, tanpa constraint duplikasi) ⇒ dikirim apa adanya (best-effort);
        * baris memakai command One2many ``(0, 0, {...})``; pajak dikirim sebagai
          **m2m command** ``tax_ids: [(6, 0, [id…])]`` — nama field barisnya
          `tax_ids` (`account.move.line`), **bukan** `taxes_id` (`purchase.order.line`);
        * ``account_id``/``product_uom_id``/``name``/``journal_id``/``currency_id``/
          ``date``/``invoice_origin`` **tidak** dikirim — Odoo menghitungnya
          (`account_id` dari produk/kategori, journal purchase otomatis, dst.);
        * ``purchase_line_id`` juga **tidak** dikirim: PO MES di Odoo masih `draft`
          ⇒ tautan baris bill ke `purchase.order.line` akan ditolak;
        * ``action_post`` **tidak** dipanggil → bill dibiarkan **draft** supaya
          akuntan memeriksa & mem-posting di UI Odoo;
        * semua kegagalan (payload tidak lengkap / error Odoo) → ``ERPResponse(ok=False)``
          — **tidak** melempar exception (pola ``push_customer_invoice``).
        """
        data = dict(payload or {})
        ref = str(data.get("ref") or "")
        missing = [name for name in ("ref", "partner_odoo_id", "lines") if not data.get(name)]
        if missing:
            return self._error(
                f"Payload vendor bill tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        try:
            partner_id = int(data["partner_odoo_id"])
        except (TypeError, ValueError):
            return self._error(
                f"partner_odoo_id tidak valid: {data['partner_odoo_id']!r}.",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        lines: list[tuple] = []
        for raw_line in data["lines"] or []:
            line = dict(raw_line or {})
            if not line.get("product_odoo_id"):
                return self._error(
                    "Setiap baris bill wajib punya product_odoo_id (sync produk dulu).",
                    stage=STAGE_VENDOR_BILL,
                    ref=ref,
                )
            try:
                quantity = float(line.get("quantity") or 0)
                price_unit = float(line.get("price_unit") or 0)
            except (TypeError, ValueError):
                return self._error(
                    "quantity/price_unit baris bill harus berupa angka.",
                    stage=STAGE_VENDOR_BILL,
                    ref=ref,
                )
            if quantity <= 0:
                return self._error(
                    "quantity baris bill harus > 0 (Odoo menolak 0).",
                    stage=STAGE_VENDOR_BILL,
                    ref=ref,
                )

            line_values: dict[str, Any] = {
                "product_id": int(line["product_odoo_id"]),
                "quantity": quantity,
                "price_unit": price_unit,
                "name": str(line.get("name") or ref),
            }
            tax_ids = [int(tax) for tax in (line.get("tax_odoo_ids") or []) if tax]
            if tax_ids:
                # m2m di dalam command One2many: set id pajak (mengganti isi).
                line_values["tax_ids"] = [(6, 0, tax_ids)]

            lines.append((0, 0, line_values))

        if not lines:
            return self._error(
                "Vendor bill tidak punya baris yang bisa dikirim (semua produk tanpa odoo_id).",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        values: dict[str, Any] = {
            "partner_id": partner_id,
            "move_type": "in_invoice",
            "invoice_date": str(data.get("invoice_date") or timezone.localdate()),
            "ref": ref,
            "invoice_line_ids": lines,
        }
        due_date = data.get("due_date")
        if due_date:
            values["invoice_date_due"] = str(due_date)

        try:
            result = self.client.execute_kw("account.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_VENDOR_BILL, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error(
                "Odoo tidak mengembalikan id account.move.",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        logger.info("OdooAdapter: VENDOR_BILL %s -> account.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_VENDOR_BILL,
            ref=ref,
        )

    def cancel_vendor_bill(self, erp_id) -> ERPResponse:
        """Batalkan vendor bill di Odoo (``account.move.button_cancel``) — H3.2.

        Dipakai saat bill MES dibatalkan **setelah** pernah terkirim (`odoo_id` ada).
        Odoo menolak dengan pesan jelas kalau move sudah diposting/pindah state
        (diteruskan apa adanya sebagai ``ok=False``); pembatalan di MES tetap sah
        (pola ``cancel_customer_invoice`` H3.1 / ``cancel_purchase_order`` H2.2).
        """
        ref = str(erp_id or "")
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        try:
            move_id = int(erp_id)
        except (TypeError, ValueError):
            return self._error(
                f"erp_id vendor bill tidak valid: {erp_id!r}.",
                stage=STAGE_VENDOR_BILL,
                ref=ref,
            )

        try:
            self.client.execute_kw("account.move", "button_cancel", [[move_id]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_VENDOR_BILL, ref=ref)

        logger.info("OdooAdapter: VENDOR_BILL cancel %s -> button_cancel", move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"cancelled": move_id},
            error=None,
            stage=STAGE_VENDOR_BILL,
            ref=ref,
        )

    # ------------------------------------------- payment MES (H3.3)
    def push_payment(self, payload: dict) -> ERPResponse:
        """Buat **payment** Odoo (`account.payment`, **draft**) dari payload eksplisit.

        ``payload`` minimal::

            {
              "payment_type": "inbound",      # atau "outbound"
              "partner_type": "customer",     # atau "supplier"
              "partner_odoo_id": 10,
              "amount": "20000.00",
              "date": "2026-10-13",
              "payment_reference": "PAY-2026-0001",   # kode MES
              "ref": "TRF-123",                       # no. referensi bank MES
              "journal_odoo_id": 13,                  # opsional (setting MES)
            }

        Aturan (probe STEP 0 H3.3 + sumber Odoo 17):

        * `account.payment` **`_inherits {'account.move': 'move_id'}`** ⇒ create payment
          otomatis membuat satu `account.move` (entry) **draft**;
        * `payment_type`/`partner_type`/`date`/`journal_id` = field **required & writable**
          ⇒ dikirim (kecuali `journal_id` yang **opsional** dari setting MES; kalau tidak
          dikirim, Odoo memilih journal sendiri lewat `_search_default_journal()`);
        * `currency_id` **computed** dari journal/company dan `payment_method_line_id`
          **computed** dari (journal × payment_type) serta dijaga constraint ⇒ keduanya
          **tidak** dikirim;
        * `memo`/`communication` **tidak ada** di Odoo 17 ⇒ kode MES dikirim lewat
          `payment_reference`, referensi bank MES lewat `ref`;
        * `reconciled_invoice_ids`/`reconciled_bill_ids` **readonly** ⇒ rekonsiliasi BUKAN
          tanggung jawab MES (akuntan Odoo yang mem-posting + merekonsiliasi);
        * `action_post` **tidak** dipanggil → payment dibiarkan **draft**;
        * semua kegagalan → ``ERPResponse(ok=False)`` (tidak melempar exception).
        """
        data = dict(payload or {})
        ref = str(data.get("payment_reference") or "")
        missing = [
            name
            for name in ("payment_type", "partner_type", "partner_odoo_id", "amount", "date")
            if not data.get(name)
        ]
        if missing:
            return self._error(
                f"Payload payment tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_PAYMENT,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_PAYMENT,
                ref=ref,
            )

        payment_type = str(data["payment_type"]).lower()
        if payment_type not in ("inbound", "outbound"):
            return self._error(
                f"payment_type tidak dikenal: {data['payment_type']!r} (inbound/outbound).",
                stage=STAGE_PAYMENT,
                ref=ref,
            )
        partner_type = str(data["partner_type"]).lower()
        if partner_type not in ("customer", "supplier"):
            return self._error(
                f"partner_type tidak dikenal: {data['partner_type']!r} (customer/supplier).",
                stage=STAGE_PAYMENT,
                ref=ref,
            )

        try:
            partner_id = int(data["partner_odoo_id"])
            amount = float(data["amount"])
        except (TypeError, ValueError):
            return self._error(
                "partner_odoo_id/amount payment harus berupa angka.",
                stage=STAGE_PAYMENT,
                ref=ref,
            )
        if amount <= 0:
            return self._error(
                "amount payment harus > 0 (Odoo menolak 0).", stage=STAGE_PAYMENT, ref=ref
            )

        values: dict[str, Any] = {
            "payment_type": payment_type,
            "partner_type": partner_type,
            "partner_id": partner_id,
            "amount": amount,
            "date": str(data["date"]),
            "payment_reference": ref,
        }
        #: Referensi bank MES → Odoo `ref` (fallback kode MES bila kosong).
        values["ref"] = str(data.get("ref") or ref)
        #: Journal HANYA bila MES dikonfigurasi (kalau tidak, Odoo memilih sendiri).
        journal_odoo_id = data.get("journal_odoo_id")
        if journal_odoo_id:
            try:
                values["journal_id"] = int(journal_odoo_id)
            except (TypeError, ValueError):
                return self._error(
                    f"journal_odoo_id tidak valid: {journal_odoo_id!r}.",
                    stage=STAGE_PAYMENT,
                    ref=ref,
                )

        try:
            result = self.client.execute_kw("account.payment", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_PAYMENT, ref=ref)

        payment_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if payment_id is None:
            return self._error(
                "Odoo tidak mengembalikan id account.payment.", stage=STAGE_PAYMENT, ref=ref
            )

        logger.info(
            "OdooAdapter: PAYMENT %s (%s) -> account.payment %s", ref, payment_type, payment_id
        )
        return ERPResponse(
            ok=True,
            erp_id=str(payment_id),
            raw={"payment_id": payment_id, "values": values},
            error=None,
            stage=STAGE_PAYMENT,
            ref=ref,
        )

    def cancel_payment(self, erp_id) -> ERPResponse:
        """Batalkan payment di Odoo (``account.payment.action_cancel``) — H3.3.

        Dipakai saat payment MES dibatalkan **setelah** pernah terkirim (`odoo_id` ada).
        Odoo menolak dengan pesan jelas kalau payment sudah diposting/direkonsiliasi
        (diteruskan apa adanya sebagai ``ok=False``); pembatalan di MES tetap sah
        (pola ``cancel_vendor_bill`` H3.2).
        """
        ref = str(erp_id or "")
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_PAYMENT,
                ref=ref,
            )

        try:
            payment_id = int(erp_id)
        except (TypeError, ValueError):
            return self._error(
                f"erp_id payment tidak valid: {erp_id!r}.", stage=STAGE_PAYMENT, ref=ref
            )

        try:
            self.client.execute_kw("account.payment", "action_cancel", [[payment_id]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_PAYMENT, ref=ref)

        logger.info("OdooAdapter: PAYMENT cancel %s -> action_cancel", payment_id)
        return ERPResponse(
            ok=True,
            erp_id=str(payment_id),
            raw={"cancelled": payment_id},
            error=None,
            stage=STAGE_PAYMENT,
            ref=ref,
        )

    # ------------------------------------------- journal entry manual (H3.4)
    def push_journal_entry(self, payload: dict) -> ERPResponse:
        """Buat **journal entry** Odoo (`account.move` `move_type='entry'`, **draft**).

        ``payload`` minimal::

            {
              "ref": "JE-2026-0001",
              "journal_odoo_id": 12,              # WAJIB (journal general)
              "date": "2026-10-13",               # WAJIB
              "lines": [
                {"account_odoo_id": 223, "name": "...", "debit": "1500.00",
                 "credit": "0.00", "partner_odoo_id": 10},   # partner opsional
                {"account_odoo_id": 178, "name": "...", "debit": "0.00",
                 "credit": "1500.00"},
              ],
            }

        Aturan (probe STEP 0 H3.4 + sumber Odoo 17):

        * ``move_type="entry"`` dikirim **eksplisit** (jangan bergantung `default_get`);
        * ``journal_id``/``date`` **required** di Odoo ⇒ divalidasi di sini;
        * baris = one2many command ``(0, 0, {...})`` berisi ``account_id`` (wajib),
          ``name``, ``debit``, ``credit``, ``partner_id`` opsional;
          ``display_type``/``currency_id`` **tidak** dikirim (default Odoo);
        * ``currency_id``/``company_id``/``narration`` **tidak** dikirim;
        * ``action_post`` **tidak** dipanggil → entry **draft** (akuntan Odoo yang posting);
        * semua kegagalan → ``ERPResponse(ok=False)`` (tidak melempar exception).
        """
        data = dict(payload or {})
        ref = str(data.get("ref") or data.get("code") or "")
        missing = [name for name in ("journal_odoo_id", "date", "lines") if not data.get(name)]
        if missing:
            return self._error(
                f"Payload journal entry tidak lengkap, field wajib: {', '.join(missing)}.",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        try:
            journal_id = int(data["journal_odoo_id"])
        except (TypeError, ValueError):
            return self._error(
                f"journal_odoo_id tidak valid: {data['journal_odoo_id']!r}.",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        lines, error = self._journal_entry_lines(data["lines"] or [], ref)
        if error:
            return self._error(error, stage=STAGE_JOURNAL_ENTRY, ref=ref)
        if len(lines) < 2:
            return self._error(
                "Journal entry butuh minimal 2 baris (debit & kredit).",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        values: dict[str, Any] = {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": str(data["date"]),
            "ref": ref,
            "line_ids": lines,
        }

        try:
            result = self.client.execute_kw("account.move", "create", [[values]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_JOURNAL_ENTRY, ref=ref)

        move_id = result[0] if isinstance(result, (list, tuple)) and result else result
        if move_id is None:
            return self._error(
                "Odoo tidak mengembalikan id account.move (entry).",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        logger.info("OdooAdapter: JOURNAL_ENTRY %s -> account.move %s", ref, move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"move_id": move_id, "values": values},
            error=None,
            stage=STAGE_JOURNAL_ENTRY,
            ref=ref,
        )

    @staticmethod
    def _journal_entry_lines(raw_lines, ref: str):
        """``(lines, error)`` — bangun one2many command baris journal entry (H3.4)."""
        lines: list[tuple] = []
        for index, raw_line in enumerate(raw_lines, start=1):
            line = dict(raw_line or {})
            if not line.get("account_odoo_id"):
                return lines, (
                    f"Baris #{index} journal entry wajib punya account_odoo_id "
                    "(pull chart of accounts dulu)."
                )
            try:
                account_id = int(line["account_odoo_id"])
                debit = float(line.get("debit") or 0)
                credit = float(line.get("credit") or 0)
            except (TypeError, ValueError):
                return lines, f"Baris #{index} journal entry tidak valid (account/debit/credit)."
            if debit == 0 and credit == 0:
                return lines, f"Baris #{index} journal entry harus punya debit atau credit (> 0)."

            line_values: dict[str, Any] = {
                "account_id": account_id,
                "name": str(line.get("name") or ref),
                "debit": debit,
                "credit": credit,
            }
            partner_odoo_id = line.get("partner_odoo_id")
            if partner_odoo_id:
                try:
                    line_values["partner_id"] = int(partner_odoo_id)
                except (TypeError, ValueError):
                    return lines, (
                        f"partner_odoo_id baris #{index} tidak valid: {partner_odoo_id!r}."
                    )

            lines.append((0, 0, line_values))

        return lines, None

    def cancel_journal_entry(self, erp_id) -> ERPResponse:
        """Batalkan journal entry di Odoo (``account.move.button_cancel``) — H3.4.

        Dipakai saat entry MES dibatalkan **setelah** pernah terkirim (``odoo_id`` ada).
        Odoo menolak dengan pesan jelas kalau move sudah diposting (diteruskan apa
        adanya sebagai ``ok=False``); pembatalan di MES tetap sah (pola H3.1–H3.3).
        """
        ref = str(erp_id or "")
        if self.client is None:
            return self._error(
                "Odoo client belum siap (kredensial ODOO_* belum lengkap).",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        try:
            move_id = int(erp_id)
        except (TypeError, ValueError):
            return self._error(
                f"erp_id journal entry tidak valid: {erp_id!r}.",
                stage=STAGE_JOURNAL_ENTRY,
                ref=ref,
            )

        try:
            self.client.execute_kw("account.move", "button_cancel", [[move_id]])
        except Exception as exc:  # noqa: BLE001 - semua error ERP -> ok=False
            return self._error(str(exc), stage=STAGE_JOURNAL_ENTRY, ref=ref)

        logger.info("OdooAdapter: JOURNAL_ENTRY cancel %s -> button_cancel", move_id)
        return ERPResponse(
            ok=True,
            erp_id=str(move_id),
            raw={"cancelled": move_id},
            error=None,
            stage=STAGE_JOURNAL_ENTRY,
            ref=ref,
        )

    @staticmethod
    def _error(message: str, *, stage: str, ref: str) -> ERPResponse:
        """ERPResponse gagal + log warning (dipakai semua jalur validasi)."""
        logger.warning("OdooAdapter: %s %s ditolak -> %s", stage, ref or "-", message)
        return ERPResponse(ok=False, erp_id=None, raw={}, error=message, stage=stage, ref=ref)


    def health_check(self) -> bool:
        """True kalau klien Odoo bisa menjawab ping; False kalau belum ada/gagal."""
        if self.client is None:
            logger.warning(
                "OdooAdapter.health_check(): client Odoo belum siap "
                "(kredensial ODOO_* kosong) -> False."
            )
            return False
        try:
            return bool(self.client.ping())
        except Exception as exc:  # noqa: BLE001 - semua kegagalan = tidak sehat
            logger.warning("OdooAdapter.health_check() gagal: %s", exc)
            return False

    def close(self) -> None:
        """Tutup klien Odoo kalau ada (aman dipanggil berkali-kali)."""
        client = self.client
        if client is not None and hasattr(client, "close"):
            client.close()


__all__ = (
    "OdooAdapter",
    "OdooJSONRPCAdapter",
    "STAGE_FG",
    "STAGE_WIP",
    "STAGE_JOURNAL_ENTRY",
)

