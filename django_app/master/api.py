"""Endpoint CRUD master Product — ``/api/v1/master/products/`` (H1.1).

Didaftarkan di ``config/urls.py`` bagian **kontrak core** (SEBELUM
``include("apps_industry.garment.api.urls")``) karena ``master`` bukan nama
industri (whitelist di ``apps_industry/garment/api/industries.py`` = ``("garmen",)``)
— tanpa pendaftaran itu path ini jatuh ke 404.

Kontrak:

  * **GET** ``/`` → ListPage ``{rows, total_count, has_more, next_cursor}``
    (paging offset-based, pola ``integrations/erp_sync/monitoring.py``).
    Query: ``?search=`` (code/name/category icontains), ``?category=``
    (icontains), ``?active=true|false``, ``?cursor=``, ``?limit=`` (1..200).
  * **POST** ``/`` → **201** + baris produk + ``sync_record_id``/``task_id``/
    ``queued`` (izin tulis: admin/owner/purchasing).
  * **GET** ``/<id>/`` → detail, **PUT** ``/<id>/`` → update (200).
  * **DELETE** ``/<id>/`` → **soft delete** (``active=False``, 200); tidak ada
    hard delete sama sekali.

Setiap baris response memuat ``odoo_id`` (frontend memakainya untuk debug sync:
``null`` = belum pernah terkirim ke Odoo). Push ke Odoo **tidak** terjadi di
sini — lihat ``master/services.py``: ``SyncRecord`` (``master.product`` +
``MASTER_PUSH``) & ``AuditLog`` ditulis dulu, task Celery di-enqueue setelahnya.
"""

from __future__ import annotations

import logging

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .bom_services import bom_detail_row, bom_row, create_bom, deactivate_bom, update_bom
from .account_services import account_row, list_queryset as account_queryset
from .journal_services import journal_row, list_queryset as journal_queryset
from .location_services import (
    create_location,
    deactivate_location,
    location_row,
    update_location,
)
from .models import BOM, Account, Journal, Location, Partner, Product, Tax, UoM, Warehouse
from .partner_services import (
    create_partner,
    deactivate_partner,
    partner_detail_row,
    partner_row,
    update_partner,
)
from .work_center_services import (
    create_work_center,
    deactivate_work_center,
    update_work_center,
    work_center_detail_row,
    work_center_row,
)
from .production_line_services import (
    create_production_line,
    deactivate_production_line,
    list_queryset as production_line_queryset,
    production_line_detail_row,
    production_line_row,
    update_production_line,
)
from .tax_services import (
    create_tax,
    deactivate_tax,
    get_default_tax,
    set_default_tax,
    tax_row,
    update_tax,
)

# H1.7 — Work Center adalah model app `garment` (bukan master), jadi diimpor
# langsung; `garment` tidak mengimpor `master` di level modul sehingga tidak ada siklus.
from apps_industry.garment.models import ProductionLine, WorkCenter
from .services import (
    MASTER_WRITE_ROLE_CODES,
    create_product,
    deactivate_product,
    parse_bool,
    price_history,
    product_row,
    update_price,
    update_product,
)
from .uom_services import create_uom, deactivate_uom, uom_row, update_uom
from .warehouse_services import (
    create_warehouse,
    deactivate_warehouse,
    update_warehouse,
    warehouse_row,
)

logger = logging.getLogger(__name__)

__all__ = (
    "MasterAccountDetailView",
    "MasterAccountListView",
    "MasterBomDetailView",
    "MasterBomListCreateView",
    "MasterJournalDetailView",
    "MasterJournalListView",
    "MasterLocationDetailView",
    "MasterLocationListCreateView",
    "MasterPartnerDetailView",
    "MasterPartnerListCreateView",
    "MasterProductionLineDetailView",
    "MasterProductionLineListCreateView",
    "MasterProductDetailView",
    "MasterProductListCreateView",
    # H3.5 — endpoint khusus harga (update + riwayat audit trail).
    "MasterProductPriceHistoryView",
    "MasterProductPriceView",
    # H3.6 — CRUD pajak (`account.tax`) + pajak default MES.
    "MasterTaxDefaultView",
    "MasterTaxDetailView",
    "MasterTaxListCreateView",
    "MasterTaxSetDefaultView",
    # H3.4 — read-only Account (chart of accounts) + Journal (buku besar).
    "MasterAccountDetailView",
    "MasterAccountListView",
    "MasterJournalDetailView",
    "MasterJournalListView",
    "MasterUomDetailView",
    "MasterWorkCenterDetailView",
    "MasterWorkCenterListCreateView",
    "MasterUomListCreateView",
    "MasterWarehouseDetailView",
    "MasterWarehouseListCreateView",
    "is_master_admin",
    "is_master_writer",
    "require_master_admin",
    "require_master_writer",
)

#: Batas paging (sama nilai dengan ``integrations/erp_sync/monitoring.py``).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
DEFAULT_OFFSET = 0
MAX_OFFSET = 100000

#: H1.2 — penulis master UoM dibatasi ADMIN/OWNER (Product juga menerima PURCHASING).
MASTER_ADMIN_ROLE_CODES = ("ADMIN", "OWNER")


def _int_param(request, name: str, default: int, minimum: int, maximum: int):
    """PURE — query param angka → ``(value, error_message)``."""
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default, None

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Parameter '{name}' harus berupa angka."

    if value < minimum or value > maximum:
        return None, f"Parameter '{name}' harus antara {minimum} dan {maximum}."

    return value, None


def _envelope(rows: list, total: int, has_more: bool, offset: int) -> dict:
    """Amplop ListPage: ``{rows, total_count, has_more, next_cursor}``."""
    return {
        "rows": rows,
        "total_count": total,
        "has_more": has_more,
        "next_cursor": (offset + len(rows)) if has_more else None,
    }


def is_master_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER/PURCHASING.

    Role dibaca dari DB (``core_auth.Role``) dan dibandingkan case-insensitive;
    role PURCHASING di-seed migration ``core_auth.0004_seed_purchasing_role``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in MASTER_WRITE_ROLE_CODES


def require_master_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil tidak boleh menulis master."""
    if not is_master_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(MASTER_WRITE_ROLE_CODES)} yang boleh mengubah master produk."
        )


def _write_body(result) -> dict:
    """Baris produk + info sinkronisasi (``sync_record_id``/``task_id``/``queued``)."""
    body = product_row(result.product)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterProductListCreateView(APIView):
    """``GET|POST /api/v1/master/products/`` — daftar & pembuatan produk (H1.1).

    * **GET** → ListPage (semua user terautentikasi; anonim **403**);
    * **POST** → **201** + baris produk (**400** body invalid/duplikat, **403**
      kalau bukan admin/owner/purchasing).

    Field baris = ``master.services.product_row`` (memuat ``odoo_id``).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List produk + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Product.objects.select_related("uom").order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(category__icontains=search)
            )

        category = str(request.query_params.get("category") or "").strip()
        if category:
            queryset = queryset.filter(category__icontains=category)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [product_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat produk; lihat docstring kelas."""
        require_master_writer(request)

        result = create_product(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.products: produk %s dibuat lewat API.", result.product.pk)
        return Response(_write_body(result), status=status.HTTP_201_CREATED)


class MasterProductDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/products/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → baris produk (404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis;
    * **DELETE** → **soft delete** (``active=False``, 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``): baris **tetap ada** di DB.

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.product``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, product_id: int):
        """Produk + relasi UoM atau ``None``."""
        return Product.objects.select_related("uom").filter(pk=product_id).first()

    def get(self, request, product_id: int):
        """Detail produk; lihat docstring kelas."""
        product = self._get(product_id)
        if product is None:
            return Response(
                {"detail": f"Produk {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(product_row(product))

    def put(self, request, product_id: int):
        """Ubah produk; lihat docstring kelas."""
        require_master_writer(request)

        product = self._get(product_id)
        if product is None:
            return Response(
                {"detail": f"Produk {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_product(product, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.products: produk %s diubah lewat API.", product_id)
        return Response(_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, product_id: int):
        """Soft delete produk (``active=False``); lihat docstring kelas."""
        require_master_writer(request)

        product = self._get(product_id)
        if product is None:
            return Response(
                {"detail": f"Produk {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_product(product, request=request)
        logger.info("master.products: produk %s dinonaktifkan lewat API.", product_id)

        return Response(
            {
                "id": product_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


class MasterProductPriceView(APIView):
    """``PUT /api/v1/master/products/<id>/price/`` — ubah **harga saja** (H3.5).

    Body minimal satu dari ``sale_price``/``cost_price`` (angka ≥ 0; **0 diizinkan**,
    negatif ditolak). Efeknya: update harga + set ``price_updated_at`` +
    ``AuditLog`` action **``master.update_price``** (metadata nilai lama → baru) +
    ``SyncRecord`` MASTER_PUSH + enqueue push ke Odoo (``list_price``/``standard_price``).

    Dipisah dari ``PUT /master/products/<id>/`` (H1.1, tetap ada & tidak diubah) supaya
    perubahan harga punya jejak audit yang granular.
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, product_id: int):
        """Ubah harga produk; lihat docstring kelas."""
        require_master_writer(request)

        product = Product.objects.select_related("uom").filter(pk=product_id).first()
        if product is None:
            return Response(
                {"detail": f"Produk {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_price(product, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.products: harga produk %s diubah lewat endpoint harga.", product_id)
        body = product_row(result.product) if result.product is not None else {}
        body["sync_record_id"] = result.sync_record_id
        body["task_id"] = result.task_id
        body["queued"] = result.queued

        return Response(body, status=status.HTTP_200_OK)


class MasterProductPriceHistoryView(APIView):
    """``GET /api/v1/master/products/<id>/price-history/`` — riwayat harga (H3.5).

    Membaca ``AuditLog`` (action ``master.update_price``) — **tanpa tabel baru**.
    Envelope §3 (``rows``/``total_count``/``has_more``/``next_cursor``) supaya UI bisa
    memakai pola list yang sama dengan resource lain.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, product_id: int):
        """Riwayat harga produk; lihat docstring kelas."""
        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            return Response(
                {"detail": f"Produk {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        history = price_history(product, limit=limit, offset=offset)

        return Response(
            _envelope(
                history["rows"],
                history["total_count"],
                offset + len(history["rows"]) < history["total_count"],
                offset,
            ),
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.2 — master UoM (`/api/v1/master/uoms/`)
# ---------------------------------------------------------------------------
def is_master_admin(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER (case-insensitive).

    Dipakai H1.2: penulis master UoM dibatasi ADMIN/OWNER (brief), sedangkan
    master Product (H1.1) juga menerima role ``purchasing``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in MASTER_ADMIN_ROLE_CODES


def require_master_admin(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_master_admin(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(MASTER_ADMIN_ROLE_CODES)} yang boleh mengubah master UoM."
        )


def _uom_write_body(result) -> dict:
    """Baris UoM + info sinkronisasi (``sync_record_id``/``task_id``/``queued``)."""
    body = uom_row(result.uom)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterUomListCreateView(APIView):
    """``GET|POST /api/v1/master/uoms/`` — daftar & pembuatan UoM (H1.2).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "category", "uom_type", "factor",
                   "rounding", "active", "odoo_id"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name/category icontains), ``?active=true|false``,
    ``?limit=`` (1..200), ``?cursor=`` (offset). Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**);
    * **POST** → **201** + baris UoM (+ info sync); izin tulis **ADMIN/OWNER**
      (**400** body invalid/duplikat, **403** role lain).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List UoM + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = UoM.objects.all().order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(category__icontains=search)
            )

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [uom_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat UoM; lihat docstring kelas."""
        require_master_admin(request)

        result = create_uom(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.uoms: UoM %s dibuat lewat API.", result.uom.pk)
        return Response(_uom_write_body(result), status=status.HTTP_201_CREATED)


class MasterUomDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/uoms/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → baris UoM (404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER;
    * **DELETE** → **soft delete** (``active=False``; 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``): baris **tetap ada** di DB.

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.uom``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, uom_id: int):
        """UoM atau ``None``."""
        return UoM.objects.filter(pk=uom_id).first()

    def get(self, request, uom_id: int):
        """Detail UoM; lihat docstring kelas."""
        uom = self._get(uom_id)
        if uom is None:
            return Response(
                {"detail": f"UoM {uom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(uom_row(uom))

    def put(self, request, uom_id: int):
        """Ubah UoM; lihat docstring kelas."""
        require_master_admin(request)

        uom = self._get(uom_id)
        if uom is None:
            return Response(
                {"detail": f"UoM {uom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_uom(uom, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.uoms: UoM %s diubah lewat API.", uom_id)
        return Response(_uom_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, uom_id: int):
        """Soft delete UoM (``active=False``); lihat docstring kelas."""
        require_master_admin(request)

        uom = self._get(uom_id)
        if uom is None:
            return Response(
                {"detail": f"UoM {uom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_uom(uom, request=request)
        logger.info("master.uoms: UoM %s dinonaktifkan lewat API.", uom_id)

        return Response(
            {
                "id": uom_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.3 — master Warehouse (`/api/v1/master/warehouses/`)
# ---------------------------------------------------------------------------
def _warehouse_write_body(result) -> dict:
    """Baris gudang + info sinkronisasi (``sync_record_id``/``task_id``/``queued``)."""
    body = warehouse_row(result.warehouse)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterWarehouseListCreateView(APIView):
    """``GET|POST /api/v1/master/warehouses/`` — daftar & pembuatan gudang (H1.3).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "reception_steps", "delivery_steps",
                   "active", "odoo_id"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?active=true|false``,
    ``?limit=`` (1..200), ``?cursor=`` (offset). Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**);
    * **POST** → **201** + baris gudang (+ info sync); izin tulis **ADMIN/OWNER**
      (**400** body invalid/duplikat, **403** role lain).

    Field ``usage`` TIDAK ada di kontrak ini — di Odoo, ``usage`` milik
    ``stock.location`` (H1.4).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List gudang + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Warehouse.objects.all().order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [warehouse_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat gudang; lihat docstring kelas."""
        require_master_admin(request)

        result = create_warehouse(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.warehouses: gudang %s dibuat lewat API.", result.warehouse.pk)
        return Response(_warehouse_write_body(result), status=status.HTTP_201_CREATED)


class MasterWarehouseDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/warehouses/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → baris gudang (404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER;
    * **DELETE** → **soft delete** (``active=False``; 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``): baris **tetap ada** di DB.

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.warehouse``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo (task update-only).
    """

    permission_classes = [IsAuthenticated]

    def _get(self, warehouse_id: int):
        """Gudang atau ``None``."""
        return Warehouse.objects.filter(pk=warehouse_id).first()

    def get(self, request, warehouse_id: int):
        """Detail gudang; lihat docstring kelas."""
        warehouse = self._get(warehouse_id)
        if warehouse is None:
            return Response(
                {"detail": f"Gudang {warehouse_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(warehouse_row(warehouse))

    def put(self, request, warehouse_id: int):
        """Ubah gudang; lihat docstring kelas."""
        require_master_admin(request)

        warehouse = self._get(warehouse_id)
        if warehouse is None:
            return Response(
                {"detail": f"Gudang {warehouse_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_warehouse(warehouse, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.warehouses: gudang %s diubah lewat API.", warehouse_id)
        return Response(_warehouse_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, warehouse_id: int):
        """Soft delete gudang (``active=False``); lihat docstring kelas."""
        require_master_admin(request)

        warehouse = self._get(warehouse_id)
        if warehouse is None:
            return Response(
                {"detail": f"Gudang {warehouse_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_warehouse(warehouse, request=request)
        logger.info("master.warehouses: gudang %s dinonaktifkan lewat API.", warehouse_id)

        return Response(
            {
                "id": warehouse_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.4 — master Location (`/api/v1/master/locations/`)
# ---------------------------------------------------------------------------
def _location_write_body(result) -> dict:
    """Baris lokasi + info sinkronisasi (``sync_record_id``/``task_id``/``queued``)."""
    body = location_row(result.location)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterLocationListCreateView(APIView):
    """``GET|POST /api/v1/master/locations/`` — daftar & pembuatan lokasi (H1.4).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "usage", "parent_id", "parent_name",
                   "warehouse_id", "warehouse_name", "active", "odoo_id",
                   "children_count", "complete_name"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?usage=``, ``?warehouse_id=``,
    ``?parent_id=``, ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=``.
    Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**); ``children_count`` dihitung
      dengan **satu** ``annotate(Count)`` (daftar anak tidak diambil — mahal);
    * **POST** → **201** + baris lokasi (+ info sync); izin tulis **ADMIN/OWNER**
      (**400** body invalid/duplikat, **403** role lain).

    ``complete_name`` = DERIVED (rantai induk), tidak ada kolomnya di DB.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List lokasi + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = (
            Location.objects.select_related("parent", "warehouse")
            .annotate(children_count=Count("children"))
            .order_by("code")
        )

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        usage = str(request.query_params.get("usage") or "").strip().lower()
        if usage:
            queryset = queryset.filter(usage=usage)

        for param, field in (("warehouse_id", "warehouse_id"), ("parent_id", "parent_id")):
            raw = request.query_params.get(param)
            if raw in (None, ""):
                continue
            try:
                queryset = queryset.filter(**{field: int(raw)})
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"Parameter '{param}' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [location_row(row, children_count=row.children_count) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat lokasi; lihat docstring kelas."""
        require_master_admin(request)

        result = create_location(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.locations: lokasi %s dibuat lewat API.", result.location.pk)
        return Response(_location_write_body(result), status=status.HTTP_201_CREATED)


class MasterLocationDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/locations/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → baris lokasi + ``children_count`` (404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER;
      induk tidak boleh dirinya sendiri / turunannya sendiri (**400**);
    * **DELETE** → **soft delete** (``active=False``; 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``), **ditolak 400** kalau lokasi masih punya
      anak **aktif** (nonaktifkan/pindahkan anak dulu); baris tetap ada di DB.

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.location``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, location_id: int):
        """Lokasi (+ induk & gudang, sekali query) atau ``None``."""
        return (
            Location.objects.select_related("parent", "warehouse")
            .filter(pk=location_id)
            .first()
        )

    def get(self, request, location_id: int):
        """Detail lokasi; lihat docstring kelas."""
        location = self._get(location_id)
        if location is None:
            return Response(
                {"detail": f"Lokasi {location_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(location_row(location, children_count=location.children.count()))

    def put(self, request, location_id: int):
        """Ubah lokasi; lihat docstring kelas."""
        require_master_admin(request)

        location = self._get(location_id)
        if location is None:
            return Response(
                {"detail": f"Lokasi {location_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_location(location, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.locations: lokasi %s diubah lewat API.", location_id)
        return Response(_location_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, location_id: int):
        """Soft delete lokasi (ditolak kalau masih punya anak aktif); lihat docstring."""
        require_master_admin(request)

        location = self._get(location_id)
        if location is None:
            return Response(
                {"detail": f"Lokasi {location_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_location(location, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.locations: lokasi %s dinonaktifkan lewat API.", location_id)

        return Response(
            {
                "id": location_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.5 — master BOM (`/api/v1/master/boms/`)
# ---------------------------------------------------------------------------
def _bom_write_body(result) -> dict:
    """Baris BOM (detail + lines) + info sinkronisasi."""
    body = bom_detail_row(result.bom)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterBomListCreateView(APIView):
    """``GET|POST /api/v1/master/boms/`` — daftar & pembuatan BOM (H1.5).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "product_id", "product_code", "product_name",
                   "output_qty", "uom_id", "uom_code", "notes", "active", "odoo_id",
                   "lines_count", "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name BOM + kode/nama produk), ``?product_id=``,
    ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=``. Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**); ``lines_count`` dihitung
      **satu** ``annotate(Count(..., filter=…is_active=True))`` — baris komponen
      tidak diambil di daftar (anti N+1);
    * **POST** → **201** + detail BOM (termasuk ``lines[]`` yang baru dibuat) +
      info sync; izin tulis **ADMIN/OWNER** (**400** validasi, **403** role lain).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List BOM + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = (
            BOM.objects.select_related("product", "uom")
            .annotate(lines_count=Count("lines", filter=Q(lines__is_active=True)))
            .order_by("code")
        )

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(product__code__icontains=search)
                | Q(product__name__icontains=search)
            )

        raw_product = request.query_params.get("product_id")
        if raw_product not in (None, ""):
            try:
                queryset = queryset.filter(product_id=int(raw_product))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'product_id' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [bom_row(row, lines_count=row.lines_count) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat BOM + ``lines[]``; lihat docstring kelas."""
        require_master_admin(request)

        result = create_bom(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.boms: BOM %s dibuat lewat API.", result.bom.pk)
        return Response(_bom_write_body(result), status=status.HTTP_201_CREATED)


class MasterBomDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/boms/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → detail BOM + ``lines[]`` (hanya baris aktif; 404 kalau tidak ada);
    * **PUT** → ubah header dan/atau **ganti seluruh** ``lines`` (200) — izin tulis
      ADMIN/OWNER; baris yang tidak lagi dikirim di-*soft-delete*, bukan dihapus;
      komponen = produk BOM sendiri (**400**) & siklus BOM (**400**);
    * **DELETE** → **soft delete** (``active=False``; 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``) — tanpa guard dependensi (tidak ada FK
      lain ke BOM; konsumen memfilter ``is_active``).

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.bom``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo (header + baris).
    """

    permission_classes = [IsAuthenticated]

    def _get(self, bom_id: int):
        """BOM (+ produk & satuan, sekali query) atau ``None``."""
        return BOM.objects.select_related("product", "uom").filter(pk=bom_id).first()

    def get(self, request, bom_id: int):
        """Detail BOM + lines; lihat docstring kelas."""
        bom = self._get(bom_id)
        if bom is None:
            return Response(
                {"detail": f"BOM {bom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(bom_detail_row(bom))

    def put(self, request, bom_id: int):
        """Ubah BOM (+ ganti baris bila ``lines`` dikirim); lihat docstring kelas."""
        require_master_admin(request)

        bom = self._get(bom_id)
        if bom is None:
            return Response(
                {"detail": f"BOM {bom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_bom(bom, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.boms: BOM %s diubah lewat API.", bom_id)
        return Response(_bom_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, bom_id: int):
        """Soft delete BOM; lihat docstring kelas."""
        require_master_admin(request)

        bom = self._get(bom_id)
        if bom is None:
            return Response(
                {"detail": f"BOM {bom_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_bom(bom, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.boms: BOM %s dinonaktifkan lewat API.", bom_id)

        return Response(
            {
                "id": bom_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.6 — master Partner (`/api/v1/master/partners/`)
# ---------------------------------------------------------------------------
def _partner_write_body(result) -> dict:
    """Baris partner (detail + ``orders_count``) + info sinkronisasi."""
    body = partner_detail_row(result.partner)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterPartnerListCreateView(APIView):
    """``GET|POST /api/v1/master/partners/`` — daftar & pembuatan partner (H1.6).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "email", "phone", "city", "address", "npwp",
                   "is_customer", "is_vendor", "is_company", "customer_rank",
                   "supplier_rank", "active", "odoo_id", "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name/email/city icontains), ``?is_customer=``,
    ``?is_vendor=``, ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=``.
    Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**);
    * **POST** → **201** + detail partner (+ ``orders_count``) + info sync; izin
      tulis **ADMIN/OWNER** (**400** validasi, **403** role lain).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List partner + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Partner.objects.all().order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(city__icontains=search)
            )

        for param, field in (("is_customer", "is_customer"), ("is_vendor", "is_vendor")):
            if request.query_params.get(param) is None:
                continue
            flag = parse_bool(request.query_params.get(param))
            if flag is None:
                return Response(
                    {"detail": f"Parameter '{param}' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(**{field: flag})

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [partner_row(partner) for partner in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat partner; lihat docstring kelas."""
        require_master_admin(request)

        result = create_partner(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.partners: partner %s dibuat lewat API.", result.partner.pk)
        return Response(_partner_write_body(result), status=status.HTTP_201_CREATED)


class MasterPartnerDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/partners/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → detail partner + ``orders_count`` (jumlah order yang memakainya
      sebagai customer; 404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER; guard peran
      ``is_customer``/``is_vendor`` tidak boleh keduanya False (**400**);
    * **DELETE** → **soft delete** (``active=False``; 200 + ``{id, active, deleted,
      sync_record_id, task_id, queued}``) tanpa guard dependensi (``Order.customer``
      memakai ``PROTECT`` dan kita tidak pernah hard delete).

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.partner``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, partner_id: int):
        """Partner atau ``None`` (tanpa relasi tambahan — tidak ada N+1)."""
        return Partner.objects.filter(pk=partner_id).first()

    def get(self, request, partner_id: int):
        """Detail partner; lihat docstring kelas."""
        partner = self._get(partner_id)
        if partner is None:
            return Response(
                {"detail": f"Partner {partner_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(partner_detail_row(partner))

    def put(self, request, partner_id: int):
        """Ubah partner; lihat docstring kelas."""
        require_master_admin(request)

        partner = self._get(partner_id)
        if partner is None:
            return Response(
                {"detail": f"Partner {partner_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_partner(partner, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.partners: partner %s diubah lewat API.", partner_id)
        return Response(_partner_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, partner_id: int):
        """Soft delete partner; lihat docstring kelas."""
        require_master_admin(request)

        partner = self._get(partner_id)
        if partner is None:
            return Response(
                {"detail": f"Partner {partner_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_partner(partner, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.partners: partner %s dinonaktifkan lewat API.", partner_id)

        return Response(
            {
                "id": partner_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.7 — master Work Center (`/api/v1/master/work-centers/`)
# ---------------------------------------------------------------------------
def _work_center_write_body(result) -> dict:
    """Baris detail work center + jejak sync (H1.7 MES-only → ``SKIPPED``)."""
    body = work_center_detail_row(result.work_center)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "sync_status": result.sync_status,
            # MES-only: tidak ada push — field ini disertakan supaya bentuk respons
            # tetap seragam dengan master lain (H1.1–H1.6) dan frontend aman.
            "task_id": None,
            "queued": False,
            "mes_only": True,
        }
    )
    return body


class MasterWorkCenterListCreateView(APIView):
    """``GET|POST /api/v1/master/work-centers/`` — daftar & pembuatan WC (H1.7).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "wc_type", "capability_tags",
                   "capacity_per_hour", "description", "active", "config",
                   "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name/wc_type icontains), ``?wc_type=`` (exact
    case-insensitive), ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=``.
    Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**);
    * **POST** → **201** + detail WC (+ ``active_bundles_count``/``production_lines``)
      + ``{sync_record_id, sync_status:'SKIPPED', mes_only:true}``; izin tulis
      **ADMIN/OWNER**; **400** validasi (code wajib/unik, name wajib, tag/angka ngawur).

    H1.7 **MES-only**: tidak ada push/pull Odoo → tidak ada task yang di-enqueue,
    ledger sync ditulis dengan status ``SKIPPED`` (terlihat di
    ``GET /api/v1/sync/records/?status=SKIPPED``).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List work center + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = WorkCenter.objects.all().order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(wc_type__icontains=search)
            )

        wc_type = str(request.query_params.get("wc_type") or "").strip()
        if wc_type:
            queryset = queryset.filter(wc_type__iexact=wc_type)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [work_center_row(work_center) for work_center in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat work center; lihat docstring kelas."""
        require_master_admin(request)

        result = create_work_center(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.work_centers: WC %s dibuat lewat API.", result.work_center.pk)
        return Response(_work_center_write_body(result), status=status.HTTP_201_CREATED)


class MasterWorkCenterDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/work-centers/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → detail WC + ``active_bundles_count`` + ``production_lines``
      (lini yang memuat WC ini; dikelola H1.8), 404 kalau tidak ada;
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER;
    * **DELETE** → **soft delete** (``active=False``; 200) dengan **guard**:
      400 kalau WC masih memegang bundle aktif (state di luar
      ``WCQueue.EXCLUDED_STATES`` = DONE/CANCELLED).

    Semua tulis menulis ``SyncRecord`` (``master.work_center``/``MASTER_PUSH``,
    status ``SKIPPED`` karena MES-only) + ``AuditLog`` — tanpa enqueue task
    (H1.7 tidak punya push Odoo).
    """

    permission_classes = [IsAuthenticated]

    def _get(self, work_center_id: int):
        """WorkCenter + prefetch lini produksinya (hindari N+1 di detail)."""
        return (
            WorkCenter.objects.filter(pk=work_center_id)
            .prefetch_related("production_lines")
            .first()
        )

    def get(self, request, work_center_id: int):
        """Detail work center; lihat docstring kelas."""
        work_center = self._get(work_center_id)
        if work_center is None:
            return Response(
                {"detail": f"Work center {work_center_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(work_center_detail_row(work_center))

    def put(self, request, work_center_id: int):
        """Ubah work center; lihat docstring kelas."""
        require_master_admin(request)

        work_center = self._get(work_center_id)
        if work_center is None:
            return Response(
                {"detail": f"Work center {work_center_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_work_center(work_center, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.work_centers: WC %s diubah lewat API.", work_center_id)
        return Response(_work_center_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, work_center_id: int):
        """Soft delete work center (guard bundle aktif); lihat docstring kelas."""
        require_master_admin(request)

        work_center = self._get(work_center_id)
        if work_center is None:
            return Response(
                {"detail": f"Work center {work_center_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_work_center(work_center, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.work_centers: WC %s dinonaktifkan lewat API.", work_center_id)

        return Response(
            {
                "id": work_center_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "sync_status": result.sync_status,
                "mes_only": True,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H1.8 — master Production Line (`/api/v1/master/production-lines/`)
# ---------------------------------------------------------------------------
def _production_line_write_body(result) -> dict:
    """Baris detail production line + jejak sync (H1.8 MES-only → ``SKIPPED``)."""
    body = production_line_detail_row(result.production_line)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "sync_status": result.sync_status,
            # MES-only: tidak ada push — field ini disertakan agar bentuk respons
            # seragam dengan master lain (H1.1–H1.7) dan frontend aman.
            "task_id": None,
            "queued": False,
            "mes_only": True,
        }
    )
    return body


class MasterProductionLineListCreateView(APIView):
    """``GET|POST /api/v1/master/production-lines/`` — daftar & buat lini (H1.8).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "description", "capability_tags",
                   "work_centers_count", "work_center_ids", "work_center_names",
                   "allocation_rules_count", "active", "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?capability_tag=`` (cocok sebagian,
    case-insensitive, di dalam list tag), ``?work_center=<id>`` (line yang memuat WC
    itu), ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=``. Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**); list memakai ``annotate``
      (``work_centers_count``/``allocation_rules_count``) + ``prefetch_related`` WC
      → tanpa N+1;
    * **POST** → **201** + detail (+ ``work_centers[]``/``active_bundles_count``) +
      ``{sync_record_id, sync_status:'SKIPPED', mes_only:true}``; izin tulis
      **ADMIN/OWNER**; **400** validasi (code wajib/unik, name wajib, tag, id WC).

    H1.8 **MES-only**: tidak ada push/pull Odoo (Odoo 17 tidak punya wadah lini) →
    ledger sync ditulis ``SKIPPED`` (lihat ``GET /api/v1/sync/records/?status=SKIPPED``).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List production line + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = production_line_queryset().prefetch_related("work_centers")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        capability_tag = str(request.query_params.get("capability_tag") or "").strip()
        if capability_tag:
            # JSONField list → cocok sebagian & case-insensitive (mis. "sewing"
            # menemukan tag "SEWING"), pola sama dengan `?search=` di master lain.
            queryset = queryset.filter(capability_tags__icontains=capability_tag)

        raw_work_center = request.query_params.get("work_center")
        if raw_work_center is not None:
            try:
                work_center_id = int(raw_work_center)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'work_center' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if work_center_id <= 0:
                return Response(
                    {"detail": "Parameter 'work_center' harus lebih besar dari 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(work_centers__pk=work_center_id)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [production_line_row(production_line) for production_line in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat production line; lihat docstring kelas."""
        require_master_admin(request)

        result = create_production_line(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "master.production_lines: line %s dibuat lewat API.", result.production_line.pk
        )
        return Response(_production_line_write_body(result), status=status.HTTP_201_CREATED)


class MasterProductionLineDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/production-lines/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → detail lini + ``work_centers[]`` (anggota, urut kode) +
      ``active_bundles_count``; 404 kalau tidak ada;
    * **PUT** → ubah field yang dikirim **dan/atau replace M2M** ``work_center_ids``
      (atomic; id WC divalidasi dulu → 400 tanpa menyentuh M2M lama);
    * **DELETE** → **soft delete** (``active=False``; 200) dengan **guard**: 400 kalau
      lini masih menampung bundle aktif (state di luar ``WCQueue.EXCLUDED_STATES``).

    Semua tulis menulis ``SyncRecord`` (``master.production_line``/``MASTER_PUSH``,
    status ``SKIPPED`` karena MES-only) + ``AuditLog`` — tanpa enqueue task.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, production_line_id: int):
        """ProductionLine + prefetch anggota WC (hindari N+1 di detail)."""
        return ProductionLine.objects.filter(pk=production_line_id).prefetch_related("work_centers").first()

    def get(self, request, production_line_id: int):
        """Detail production line; lihat docstring kelas."""
        production_line = self._get(production_line_id)
        if production_line is None:
            return Response(
                {"detail": f"Production line {production_line_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(production_line_detail_row(production_line))

    def put(self, request, production_line_id: int):
        """Ubah production line (termasuk replace M2M); lihat docstring kelas."""
        require_master_admin(request)

        production_line = self._get(production_line_id)
        if production_line is None:
            return Response(
                {"detail": f"Production line {production_line_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_production_line(production_line, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.production_lines: line %s diubah lewat API.", production_line_id)
        return Response(_production_line_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, production_line_id: int):
        """Soft delete production line (guard bundle aktif); lihat docstring kelas."""
        require_master_admin(request)

        production_line = self._get(production_line_id)
        if production_line is None:
            return Response(
                {"detail": f"Production line {production_line_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_production_line(production_line, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "master.production_lines: line %s dinonaktifkan lewat API.", production_line_id
        )

        return Response(
            {
                "id": production_line_id,
                "active": False,
                "deleted": True,
                "sync_record_id": result.sync_record_id,
                "sync_status": result.sync_status,
                "mes_only": True,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# H3.6 — master Tax (`/api/v1/master/taxes/`)
# ---------------------------------------------------------------------------
def _tax_write_body(result) -> dict:
    """Baris Tax + info sinkronisasi (``sync_record_id``/``task_id``/``queued``)."""
    body = tax_row(result.tax)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )
    return body


class MasterTaxListCreateView(APIView):
    """``GET|POST /api/v1/master/taxes/`` — daftar & pembuatan pajak (H3.6).

    Bentuk ListPage::

        {"rows": [{"id", "code", "name", "amount", "amount_type", "type_tax_use",
                   "price_include", "is_default", "active", "odoo_id"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?type_tax_use=sale|purchase|none``,
    ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=`` (offset). Urut ``code``.

    * **GET** → semua user terautentikasi (anon **403**) — dipakai dropdown form
      SO/PO (H2.1/H2.2) maupun halaman master;
    * **POST** → **201** + baris Tax (+ info sync); izin tulis **ADMIN/OWNER**
      (**400** body invalid/duplikat kode, **403** role lain).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List pajak + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Tax.objects.all().order_by("code")

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        type_tax_use = str(request.query_params.get("type_tax_use") or "").strip().lower()
        if type_tax_use:
            if type_tax_use not in Tax.TaxUse.values:
                return Response(
                    {
                        "detail": (
                            "Parameter 'type_tax_use' harus salah satu dari "
                            f"{', '.join(Tax.TaxUse.values)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(type_tax_use=type_tax_use)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [tax_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )

    def post(self, request):
        """Buat pajak; lihat docstring kelas."""
        require_master_admin(request)

        result = create_tax(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.taxes: Tax %s dibuat lewat API.", result.tax.pk)
        return Response(_tax_write_body(result), status=status.HTTP_201_CREATED)


class MasterTaxDefaultView(APIView):
    """``GET /api/v1/master/taxes/default/`` — pajak default MES (H3.6).

    Dipakai form SO/PO (H2.1/H2.2) & invoice (H3.1) untuk mengisi ``tax_ids``
    otomatis. Fallback service: penanda ``is_default`` → PPN 11% penjualan → pajak
    aktif pertama; ``{"tax": null}`` kalau belum ada pajak sama sekali.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Kembalikan pajak default (atau ``null``); lihat docstring kelas."""
        tax = get_default_tax()
        return Response({"tax": tax_row(tax) if tax is not None else None})


class MasterTaxDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/master/taxes/<id>/`` — detail, ubah, nonaktifkan.

    * **GET** → baris pajak (404 kalau tidak ada);
    * **PUT** → ubah field yang dikirim (200) — izin tulis ADMIN/OWNER;
    * **DELETE** → **soft delete** (``active=False``; penanda ``is_default``
      dilepas) — baris **tetap ada** di DB supaya relasi ``tax_ids`` H2.1/H2.2 utuh.

    Setiap PUT/DELETE menulis ``SyncRecord`` (``master.tax``/``MASTER_PUSH``)
    + ``AuditLog`` lalu meng-enqueue push async ke Odoo.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, tax_id: int):
        """Tax atau ``None``."""
        return Tax.objects.filter(pk=tax_id).first()

    def get(self, request, tax_id: int):
        """Detail pajak; lihat docstring kelas."""
        tax = self._get(tax_id)
        if tax is None:
            return Response(
                {"detail": f"Tax {tax_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(tax_row(tax))

    def put(self, request, tax_id: int):
        """Ubah pajak; lihat docstring kelas."""
        require_master_admin(request)

        tax = self._get(tax_id)
        if tax is None:
            return Response(
                {"detail": f"Tax {tax_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = update_tax(tax, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.taxes: Tax %s diubah lewat API.", tax_id)
        return Response(_tax_write_body(result), status=status.HTTP_200_OK)

    def delete(self, request, tax_id: int):
        """Soft delete pajak (``active=False``); lihat docstring kelas."""
        require_master_admin(request)

        tax = self._get(tax_id)
        if tax is None:
            return Response(
                {"detail": f"Tax {tax_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = deactivate_tax(tax, request=request)
        logger.info("master.taxes: Tax %s dinonaktifkan lewat API.", tax_id)

        return Response(
            {
                "id": tax_id,
                "active": False,
                "deleted": True,
                "is_default": False,
                "sync_record_id": result.sync_record_id,
                "task_id": result.task_id,
                "queued": result.queued,
            },
            status=status.HTTP_200_OK,
        )


class MasterTaxSetDefaultView(APIView):
    """``POST /api/v1/master/taxes/<id>/set-default/`` — jadikan pajak default MES.

    Atomik (satu transaksi): semua baris lain di-unset, baris ini di-set — sehingga
    selalu **maksimal satu** pajak ``is_default=True``. ``is_default`` bukan field
    Odoo, jadi operasi ini **tidak** memicu push (hanya ``AuditLog``).

    * **200** → baris pajak terbaru; **404** kalau id tidak ada; **400** kalau pajak
      nonaktif; **403** kalau bukan ADMIN/OWNER.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, tax_id: int):
        """Set pajak default; lihat docstring kelas."""
        require_master_admin(request)

        tax = Tax.objects.filter(pk=tax_id).first()
        if tax is None:
            return Response(
                {"detail": f"Tax {tax_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = set_default_tax(tax, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("master.taxes: Tax %s dijadikan default lewat API.", tax_id)
        return Response(tax_row(result.tax), status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# H3.4 — read-only Account / chart of accounts (`/api/v1/master/accounts/`)
# ---------------------------------------------------------------------------
class MasterAccountListView(APIView):
    """``GET /api/v1/master/accounts/`` — daftar akun buku besar (H3.4, **read-only**).

    Bentuk ListPage::

        {"rows": [{"id", "odoo_id", "code", "name", "account_type",
                   "account_type_label", "reconcile", "active"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?account_type=`` (salah satu dari 18
    tipe Odoo), ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=`` (offset).
    Urut ``code``.

    Sumber data = hasil *pull* ``erp_sync.sync_master_accounts`` (Odoo
    ``account.account``). **Tidak** ada POST/PUT/DELETE: chart of accounts hanya
    boleh diubah akuntan di Odoo (keputusan STEP 0 H3.4) — request tulis = **405**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List akun + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = account_queryset()

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        account_type = str(request.query_params.get("account_type") or "").strip().lower()
        if account_type:
            if account_type not in Account.AccountType.values:
                return Response(
                    {
                        "detail": (
                            "Parameter 'account_type' harus salah satu dari "
                            f"{', '.join(Account.AccountType.values)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(account_type=account_type)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [account_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )


class MasterAccountDetailView(APIView):
    """``GET /api/v1/master/accounts/<id>/`` — detail satu akun (H3.4, read-only).

    Dipakai form Journal Entry untuk memastikan akun terpilih sudah punya
    ``odoo_id`` (prasyarat push). **404** kalau tidak ada; tidak ada PUT/DELETE.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, account_id: int):
        """Detail akun; lihat docstring kelas."""
        account = Account.objects.filter(pk=account_id).first()
        if account is None:
            return Response(
                {"detail": f"Account {account_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(account_row(account))


# ---------------------------------------------------------------------------
# H3.4 — read-only Journal (`/api/v1/master/journals/`)
# ---------------------------------------------------------------------------
class MasterJournalListView(APIView):
    """``GET /api/v1/master/journals/`` — daftar jurnal/buku besar (H3.4, **read-only**).

    Bentuk ListPage::

        {"rows": [{"id", "odoo_id", "code", "name", "journal_type",
                   "journal_type_label", "is_general", "active"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?search=`` (code/name icontains), ``?type=general|sale|purchase|bank|cash``,
    ``?active=true|false``, ``?limit=`` (1..200), ``?cursor=`` (offset). Urut ``code``.

    Dipakai form Journal Entry H3.4 (filter ``type=general``). Data = mirror I1
    (``master.Journal``) + field aditif ``journal_type`` hasil pull Odoo. **Tidak**
    ada POST/PUT/DELETE — journal adalah konfigurasi akuntansi Odoo.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List journal + filter; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = journal_queryset()

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))

        journal_type = str(request.query_params.get("type") or "").strip().lower()
        if journal_type:
            if journal_type not in Journal.JournalType.values:
                return Response(
                    {
                        "detail": (
                            "Parameter 'type' harus salah satu dari "
                            f"{', '.join(Journal.JournalType.values)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(journal_type=journal_type)

        if request.query_params.get("active") is not None:
            active = parse_bool(request.query_params.get("active"))
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope(
                [journal_row(row) for row in rows],
                total,
                offset + len(rows) < total,
                offset,
            )
        )


class MasterJournalDetailView(APIView):
    """``GET /api/v1/master/journals/<id>/`` — detail satu jurnal (H3.4, read-only).

    ``404`` kalau tidak ada; tidak ada PUT/DELETE (pola `MasterAccountDetailView`).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, journal_id: int):
        """Detail journal; lihat docstring kelas."""
        journal = Journal.objects.filter(pk=journal_id).first()
        if journal is None:
            return Response(
                {"detail": f"Journal {journal_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(journal_row(journal))

