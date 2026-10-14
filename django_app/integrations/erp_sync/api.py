"""Endpoint sync manual ke Odoo: `POST /api/v1/sync/odoo/<stage>/` (Kontrak §7).

Kenapa di `integrations/` (bukan `apps_industry/garment/api/`): sinkronisasi ERP
adalah layanan **core/integrasi**, bukan aturan bisnis garmen — industri lain di
masa depan memakai endpoint yang sama.

Alur view:

  1. ``stage`` dinormalisasi ke uppercase; hanya ``WIP`` / ``FG`` (400 kalau lain);
  2. validasi body: ``resource`` (``bundle`` / ``work_order``), ``resource_id``,
     dan ``payload`` (object JSON, tidak kosong) -> 400 kalau kurang;
  3. idempotency opsional (header ``Idempotency-Key``, pola sama seperti endpoint
     aksi Fase 3): key yang sudah pernah sukses -> response pertama apa adanya +
     ``X-Idempotent-Replay: true`` + ``{"duplicate-ignored": true}``;
  4. ``SyncIdempotency.get_or_create_sync_record``; kalau record sudah
     ``SENT``/``DUPLICATE`` -> balas ``duplicate-ignored`` tanpa enqueue ulang
     (stok tidak boleh dobel);
  5. enqueue Celery (``erp_sync.push_wip_issue`` / ``push_fg_receipt``) dan balas
     **200 async** berisi ``task_id`` (frontend tidak menunggu ERP).
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import MaterialReadiness, Order, OrderLine
from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from core.idempotency.services import IdempotencyService

from .idempotency import STAGE_FG, STAGE_WIP, SyncIdempotency
from .models import SyncResource
from .services import (
    MaterialReadinessService,
    ProductAuditService,
    ReconciliationService,
    ScrapSyncService,
)
from .tasks import push_fg_receipt, push_wip_issue
from .tasks_master import (
    sync_master_accounts,
    sync_master_boms,
    sync_master_currencies,
    sync_master_journals,
    sync_master_locations,
    sync_master_partners,
    sync_master_products,
    sync_master_taxes,
    sync_master_uoms,
    sync_master_warehouses,
)

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"

#: Stage valid (uppercase) -> task Celery-nya.
STAGE_TASKS = {
    STAGE_WIP: push_wip_issue,
    STAGE_FG: push_fg_receipt,
}

#: Resource yang **boleh** lewat endpoint two-stage ini (lihat I8.3).
#: ``STAGE_TASKS`` hanya berisi stage WIP/FG, jadi resource yang masuk akal
#: hanyalah ``bundle`` & ``work_order`` — sedangkan ``scrap_accumulator``
#: punya endpoint sendiri (``/api/v1/sync/scrap/``) dan ``order`` dibuat
#: otomatis oleh listener WO selesai. Sebelumnya validasi hanya memakai
#: ``SyncResource.values`` sehingga ``scrap_accumulator`` lolos diam-diam.
STAGE_RESOURCES = (SyncResource.BUNDLE.value, SyncResource.WORK_ORDER.value)

#: Petunjuk kanal/endpoint yang benar untuk resource di luar ``STAGE_RESOURCES``.
RESOURCE_HINTS = {
    SyncResource.SCRAP_ACCUMULATOR.value: "/api/v1/sync/scrap/",
    SyncResource.ORDER.value: (
        "listener WORK_ORDER_STATE_CHANGED (invoice dibuat otomatis saat semua "
        "WorkOrder selesai)"
    ),
}

#: Entity master valid -> task Celery di ``tasks_master`` (``name=`` ``erp_sync.sync_master_*``).
MASTER_TASKS = {
    "products": sync_master_products,
    "boms": sync_master_boms,
    "partners": sync_master_partners,
    "locations": sync_master_locations,
    "taxes": sync_master_taxes,
    "uoms": sync_master_uoms,
    "warehouses": sync_master_warehouses,
    "journals": sync_master_journals,
    "currencies": sync_master_currencies,
    # H3.4 — chart of accounts (`account.account`, pull-only) untuk form Journal Entry.
    "accounts": sync_master_accounts,
}


class SyncOdooView(APIView):
    """Trigger **two-stage** sync stok ke Odoo (async lewat Celery).

    Endpoint ini khusus stage ``WIP`` (issue bahan) & ``FG`` (receipt barang
    jadi), sehingga resource yang didukung hanya ``bundle`` & ``work_order``
    (lihat ``STAGE_RESOURCES``). Resource lain yang **valid** di
    ``SyncResource`` tapi bukan jalur two-stage dibalas **400** dengan petunjuk
    kanal yang benar — mis. ``scrap_accumulator`` → ``/api/v1/sync/scrap/``
    (dulu lolos diam-diam; diperbaiki di I8.3).

    Permission ``IsAuthenticated`` (I8.5) — konsisten dengan endpoint sync lain
    (``SyncMasterView``/``SyncScrapView``/``OrderReadinessView``/
    ``ReconciliationReportView``); sebelumnya ``AllowAny`` sehingga request
    anonim bisa meng-antre task ke Celery.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, stage: str):
        """Terima permintaan sync; lihat docstring modul untuk alurnya."""
        # NB: JANGAN baca `request.body` di sini. Di server ASGI live stream body
        # sudah dikonsumsi sebelum view jalan sehingga `request.body` melempar
        # RawPostDataException (500, padahal body valid). Field diambil dari
        # `request.data` (di bawah) dan hash idempotensi dihitung dari `data`.
        stage_code = str(stage or "").strip().upper()
        task = STAGE_TASKS.get(stage_code)
        if task is None:
            return Response(
                {
                    "detail": (
                        f"Stage '{stage}' tidak dikenal. Gunakan "
                        f"{' atau '.join(sorted(STAGE_TASKS))}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data if isinstance(request.data, dict) else {}
        resource = str(data.get("resource") or "").strip().lower()
        resource_id = str(data.get("resource_id") or "").strip()
        payload = data.get("payload")

        if resource not in SyncResource.values:
            return Response(
                {
                    "detail": (
                        "Field 'resource' harus salah satu dari "
                        f"{', '.join(SyncResource.values)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Resource yang valid di enum tapi bukan jalur two-stage (mis.
        # `scrap_accumulator`) ditolak eksplisit — jangan sampai lolos ke
        # task WIP/FG (utang teknis I8.3 yang diperbaiki di sini).
        if resource not in STAGE_RESOURCES:
            hint = RESOURCE_HINTS.get(resource)
            detail = (
                f"Resource '{resource}' tidak didukung endpoint ini; pakai {hint}."
                if hint
                else (
                    f"Resource '{resource}' tidak didukung endpoint ini "
                    f"(khusus two-stage WIP/FG). Gunakan "
                    f"{' atau '.join(STAGE_RESOURCES)}."
                )
            )
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        if not resource_id:
            return Response(
                {"detail": "Field 'resource_id' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(payload, dict) or not payload:
            return Response(
                {"detail": "Field 'payload' wajib berupa object JSON dan tidak kosong."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = f"SYNC_{stage_code}"
        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        request_hash = self._request_hash(
            request.method, stage_code, resource, resource_id, data
        )
        service = IdempotencyService()

        if not idempotency_key:
            logger.warning(
                "sync %s/%s#%s tanpa header Idempotency-Key (kontrak §10 "
                "menyarankan selalu mengirim).",
                stage_code,
                resource,
                resource_id,
            )

        replay = service.check(idempotency_key, resource, resource_id, action, request_hash)
        if replay is not None:
            body = dict(replay.response_body or {})
            body["duplicate-ignored"] = True
            response = Response(body, status=replay.response_status)
            response["X-Idempotent-Replay"] = "true"
            logger.info(
                "sync: replay key '%s' untuk %s#%s:%s.",
                idempotency_key,
                resource,
                resource_id,
                action,
            )
            return response

        sync = SyncIdempotency()
        record = sync.get_or_create_sync_record(resource, resource_id, stage_code, payload)

        if sync.is_already_sent(record):
            body = {
                "ok": True,
                "status": "duplicate-ignored",
                "duplicate-ignored": True,
                "sync_record_id": record.pk,
                "erp_id": record.erp_id,
                "stage": stage_code,
                "resource": resource,
                "resource_id": resource_id,
            }
            self._save_idempotency(
                service, idempotency_key, resource, resource_id, action, request_hash, body
            )
            self._audit(
                request,
                action,
                resource,
                resource_id,
                payload,
                AuditLog.Result.OK,
                {"status": "duplicate-ignored", "erp_id": record.erp_id},
            )
            logger.info(
                "sync: %s#%s:%s sudah terkirim -> tidak di-queue ulang.",
                resource,
                resource_id,
                stage_code,
            )
            return Response(body, status=status.HTTP_200_OK)

        async_result = task.apply_async(
            args=[resource, resource_id, payload, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        body = {
            "ok": True,
            "status": "queued",
            "task_id": str(async_result.id),
            "sync_record_id": record.pk,
            "stage": stage_code,
            "resource": resource,
            "resource_id": resource_id,
        }
        self._save_idempotency(
            service, idempotency_key, resource, resource_id, action, request_hash, body
        )
        self._audit(
            request,
            action,
            resource,
            resource_id,
            payload,
            AuditLog.Result.OK,
            {"status": "queued", "task_id": body["task_id"]},
        )
        logger.info(
            "sync: %s %s#%s di-queue (task_id=%s, record=%s).",
            stage_code,
            resource,
            resource_id,
            body["task_id"],
            record.pk,
        )
        return Response(body, status=status.HTTP_200_OK)

    # --------------------------------------------------------------- internal
    @staticmethod
    def _audit(
        request,
        action: str,
        resource: str,
        resource_id: str,
        payload: dict,
        result: str,
        metadata: dict,
    ) -> None:
        """Tulis AuditLog untuk permintaan sync ini (Fase 6).

        Kegagalan audit tidak boleh menggagalkan permintaan sync yang sudah
        berhasil, jadi exception di sini hanya dicatat di log.
        """
        try:
            AuditLogger().log(
                user=None,  # diambil dari request kalau sudah terautentikasi
                action=action,
                resource=resource,
                resource_id=resource_id,
                request=request,
                payload=payload,
                result=result,
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001 - audit tidak boleh mematikan alur produksi
            logger.exception("audit: gagal mencatat sync %s %s#%s", action, resource, resource_id)

    @staticmethod
    def _save_idempotency(
        service: IdempotencyService,
        key: str | None,
        resource: str,
        resource_id: str,
        action: str,
        request_hash: str,
        body: dict,
    ) -> None:
        """Simpan response 200 supaya request ulang dengan key sama jadi replay."""
        if not key:
            return
        service.save(key, resource, resource_id, action, request_hash, 200, body)

    @staticmethod
    def _request_hash(
        method: str, stage: str, resource: str, resource_id: str, body_data: dict
    ) -> str:
        """SHA-256 dari method+stage+resource+id+body (deteksi key dipakai ulang).

        Body diambil dari ``request.data`` (dict) lalu di-serialize sebagai
        **canonical JSON** (``sort_keys`` + separator rapat) — BUKAN dari
        ``request.body``: di server ASGI live stream body sudah dikonsumsi
        sebelum view jalan, sehingga ``request.body`` melempar
        ``RawPostDataException``. Canonical supaya urutan key/spasi tidak
        mengubah hash.
        """
        canonical = json.dumps(body_data or {}, sort_keys=True, separators=(",", ":"))
        raw = f"{method}|{stage}|{resource}|{resource_id}|{canonical}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SyncMasterView(APIView):
    """Trigger manual sync **master data** per entity (async lewat Celery).

    ``POST /api/v1/sync/master/<entity>/`` → enqueue task
    ``erp_sync.sync_master_*`` (lihat :data:`MASTER_TASKS`) lalu balas
    ``{"status": "queued", "task_id": <id>}``.

    * entity tak dikenal → **404**;
    * method selain ``POST`` → **405** (bawaan ``APIView``);
    * permission ``IsAuthenticated``: repo **tidak punya** permission admin
      (seluruh endpoint sync ERP kini ``IsAuthenticated``) → dipakai
      ``IsAuthenticated`` sesuai
      instruksi; konsekuensinya request tanpa kredensial → 403.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, entity: str):  # noqa: ARG002 - request tak dipakai langsung
        """Enqueue task sync master sesuai ``entity`` (lihat :data:`MASTER_TASKS`)."""
        task = MASTER_TASKS.get(str(entity or "").strip().lower())
        if task is None:
            return Response(
                {
                    "detail": (
                        f"Entity '{entity}' tidak dikenal. Gunakan "
                        f"{', '.join(sorted(MASTER_TASKS))}."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        async_result = task.delay()
        logger.info(
            "sync master: entity %s di-queue (task_id=%s).", entity, async_result.id
        )
        return Response(
            {"status": "queued", "task_id": str(async_result.id)},
            status=status.HTTP_200_OK,
        )


class OrderReadinessView(APIView):
    """Kesiapan material satu Order: **baca** (GET) atau **recompute** (POST).

    ``GET /api/v1/garmen/orders/<order_id>/readiness/``
        Daftar per **OrderLine** milik order tsb:
        ``{order_id, lines: [{order_line_id, product_code, required_qty,
        received_qty, shortage_qty, status, expected_date, last_computed_at}]}``.
        OrderLine yang belum pernah dihitung tetap muncul dengan nilai ``null``
        (supaya supervisor melihat baris mana yang belum dihitung). Order tidak
        ada → **404**.

    ``POST /api/v1/garmen/orders/<order_id>/recompute-readiness/``
        Hitung ulang lewat :class:`~integrations.erp_sync.services.MaterialReadinessService`
        **hanya** untuk OrderLine yang **belum punya** readiness atau statusnya
        belum ``READY``; balas counter
        ``{processed, waiting, partial, ready, errors}``. Order tidak ada → **404**.

    Readiness dihitung **on-demand**: PO Odoo di-fetch lewat service → transport
    (MES tidak punya model ``PurchaseOrder``). Tanpa serializer — dict literal
    (pola repo). Permission ``IsAuthenticated`` (konsisten ``SyncMasterView``)
    → request anonim **403**.

    Kedua path didaftarkan ke view ini di ``config/urls.py`` (section kontrak
    core, SEBELUM include industri) supaya tidak tertangkap pola
    ``v1/<industry>/<resource>/<id>/<action>/``.
    """

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------------- endpoints
    def get(self, request, order_id: int):  # noqa: ARG002 - request tak dipakai
        """Baca readiness seluruh OrderLine order (belum dihitung → ``null``)."""
        order = self._get_order(order_id)
        if order is None:
            return self._not_found(order_id)

        readiness_by_line = {
            readiness.order_line_id: readiness
            for readiness in MaterialReadiness.objects.filter(
                order_line__order=order
            ).select_related("order_line__product")
        }
        lines = [
            self._line_payload(order_line, readiness_by_line.get(order_line.pk))
            for order_line in OrderLine.objects.filter(order=order)
            .select_related("product")
            .order_by("id")
        ]
        return Response(
            {"order_id": order.pk, "lines": lines}, status=status.HTTP_200_OK
        )

    def post(self, request, order_id: int):  # noqa: ARG002 - request tak dipakai
        """Recompute readiness OrderLine yang belum ada / belum ``READY``."""
        order = self._get_order(order_id)
        if order is None:
            return self._not_found(order_id)

        # `readiness__isnull=True` eksplisit: `~Q(readiness__status=READY)` saja
        # tidak menjamin baris TANPA readiness ikut terambil (semantik NULL SQL).
        order_lines = (
            OrderLine.objects.filter(order=order)
            .filter(Q(readiness__isnull=True) | ~Q(readiness__status="READY"))
            .order_by("id")
        )
        result = MaterialReadinessService().compute_batch(order_lines)
        logger.info(
            "recompute readiness: order %s -> %s (%s OrderLine dikirim).",
            order.pk,
            result,
            order_lines.count(),
        )
        return Response(result, status=status.HTTP_200_OK)

    # --------------------------------------------------------------- internal
    @staticmethod
    def _get_order(order_id: int):
        """``Order`` atau ``None`` (dasar 404)."""
        return Order.objects.filter(pk=order_id).first()

    @staticmethod
    def _not_found(order_id: int) -> Response:
        """Response 404 standar untuk order yang tidak ada."""
        return Response(
            {"detail": f"Order {order_id} tidak ditemukan."},
            status=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _line_payload(order_line, readiness) -> dict:
        """Dict satu OrderLine (``readiness`` boleh ``None``)."""
        return {
            "order_line_id": order_line.pk,
            "product_code": (
                order_line.product.code if order_line.product_id else None
            ),
            "required_qty": readiness.required_qty if readiness else None,
            "received_qty": readiness.received_qty if readiness else None,
            "shortage_qty": readiness.shortage_qty if readiness else None,
            "status": readiness.status if readiness else None,
            "expected_date": readiness.expected_date if readiness else None,
            "last_computed_at": readiness.last_computed_at if readiness else None,
            "vendor_bill_status": readiness.vendor_bill_status if readiness else None,
            "vendor_bill_ids": readiness.vendor_bill_ids if readiness else None,
            "vendor_bill_amount": readiness.vendor_bill_amount if readiness else None,
        }


class SyncScrapView(APIView):
    """Trigger sync **scrap** (TX-SCRAP) manual — sinkron, bukan enqueue Celery.

    ``POST /api/v1/sync/scrap/`` → ``ScrapSyncService().sync_batch()``: mengirim
    semua ``ScrapAccumulator`` yang ``qty > 0`` dan belum ``SENT`` ke Odoo lewat
    adapter (idempotensi via ``SyncRecord(resource="scrap_accumulator",
    stage="SCRAP")``) → balas counter ``{"sent", "failed", "skipped"}``.

    * permission ``IsAuthenticated`` (konsisten ``SyncMasterView``) → anonim **403**;
    * ``GET`` (method lain) → **405** otomatis (``get()`` tidak didefinisikan);
    * dijalankan **sinkron** supaya pemanggil langsung tahu hasilnya; jadwal
      otomatis tetap ada di Celery beat (``erp_sync.sync_scrap_accumulator``,
      06:00/14:00/22:00 WIB) — endpoint ini untuk trigger manual supervisor.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):  # noqa: ARG002 - request tak dipakai
        """Kirim semua ScrapAccumulator pending; lihat docstring kelas."""
        result = ScrapSyncService().sync_batch()
        logger.info("sync scrap manual: %s", result)
        return Response(result, status=status.HTTP_200_OK)


class ReconciliationReportView(APIView):
    """Riwayat rekonsiliasi stok MES vs Odoo (fase I7) — **read-only**.

    ``GET /api/v1/reconciliation/report/?days=7``
        Riwayat baris ``StockReconciliation`` ``days`` hari terakhir lewat
        :meth:`~integrations.erp_sync.services.ReconciliationService.report`
        (service dipanggil **apa adanya**, tanpa serializer — dict literal):
        ``{days, count, entries: [{run_at, product_code, product_odoo_id,
        mes_qty, odoo_qty, diff, is_alert, notes}]}``.

    * ``days`` **default 7**; hanya ``1..90`` yang diterima — di luar rentang itu
      (atau bukan angka) → **400**, dan service **tidak** dipanggil;
    * permission ``IsAuthenticated`` (konsisten ``SyncMasterView``/
      ``OrderReadinessView``) → request anonim **403**;
    * tanpa ``get`` lain: ``POST``/``PUT``/``PATCH``/``DELETE`` → **405** otomatis;
    * **tidak** memicu rekonsiliasi — trigger-nya Celery beat mingguan
      (``erp_sync.reconcile_stock``, Senin 03:00 WIB) atau ``apply()`` manual;
      endpoint ini murni membaca DB (tidak menyentuh Odoo).

    Didaftarkan di ``config/urls.py`` section kontrak core (SEBELUM include
    industri) supaya tidak tertangkap pola ``v1/<industry>/<resource>/...``.
    """

    permission_classes = [IsAuthenticated]

    #: Rentang `days` yang diterima (di luar ini → 400).
    MIN_DAYS = 1
    MAX_DAYS = 90
    #: Nilai `days` kalau query param tidak dikirim.
    DEFAULT_DAYS = 7

    # --------------------------------------------------------------- endpoints
    def get(self, request):
        """Baca riwayat rekonsiliasi; lihat docstring kelas."""
        days, error = self._parse_days(request)
        if error is not None:
            return error

        entries = ReconciliationService().report(days=days)
        logger.info(
            "reconciliation report: days=%s -> %s entri.", days, len(entries)
        )
        return Response(
            {"days": days, "count": len(entries), "entries": entries},
            status=status.HTTP_200_OK,
        )

    # --------------------------------------------------------------- internal
    @classmethod
    def _parse_days(cls, request):
        """``(days, None)`` kalau valid, atau ``(None, Response 400)``.

        Sengaja **tanpa** fallback diam-diam ke default: nilai di luar
        ``MIN_DAYS..MAX_DAYS`` (atau bukan angka) dibalas 400 supaya klien tahu
        permintaannya tidak dilayani (bukan mengembalikan 7 hari tanpa jejak).
        """
        raw = request.query_params.get("days")
        if raw is None or str(raw).strip() == "":
            return cls.DEFAULT_DAYS, None
        try:
            days = int(str(raw).strip())
        except (TypeError, ValueError):
            return None, cls._bad_days(raw)
        if days < cls.MIN_DAYS or days > cls.MAX_DAYS:
            return None, cls._bad_days(raw)
        return days, None

    @classmethod
    def _bad_days(cls, raw) -> Response:
        """Response 400 standar untuk ``days`` yang tidak valid."""
        return Response(
            {
                "detail": (
                    f"Parameter days={raw!r} tidak valid — harus bilangan bulat "
                    f"{cls.MIN_DAYS}..{cls.MAX_DAYS}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class ProductAuditView(APIView):
    """Audit produk master tanpa ``odoo_id`` (fase I8.8) — **read-only**.

    ``GET /api/v1/audit/products-missing-odoo-id/``
        ``{count, products, used_in_open_bundles}`` dari
        :class:`~integrations.erp_sync.services.ProductAuditService` (tanpa
        serializer — dict literal): ``count``/``products`` = produk yang belum
        punya ``odoo_id`` (daftar dipotong 100), ``used_in_open_bundles`` =
        subset yang sedang dipakai bundle di lantai (state bukan ``DONE``/
        ``DRAFT``) sehingga paling mendesak.

    Kenapa perlu: produk tanpa ``odoo_id`` **tidak ikut** rekonsiliasi stok
    (``ReconciliationService`` memfilter ``Product.odoo_id``) dan tidak bisa
    ditautkan ke baris PO/vendor bill/invoice Odoo — endpoint ini membuat
    "data kurang" terlihat sebelum user melaporkannya.

    * permission ``IsAuthenticated`` (konsisten endpoint ERP lain) → anonim 403;
    * ``POST``/``PUT``/``PATCH``/``DELETE`` → **405** otomatis;
    * **tidak** menyentuh Odoo dan **tidak** mengubah produk (audit saja);
      pengisian ``odoo_id`` tetap lewat ``erp_sync.sync_master_products``.

    Didaftarkan di ``config/urls.py`` section kontrak core (SEBELUM include
    industri) supaya tidak dianggap pola ``v1/<industry>/...``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Jalankan audit produk; lihat docstring kelas."""
        result = ProductAuditService().audit()
        logger.info(
            "audit produk: %s tanpa odoo_id, %s di antaranya dipakai bundle terbuka.",
            result["count"],
            result["used_in_open_bundles"]["count"],
        )
        return Response(result, status=status.HTTP_200_OK)

