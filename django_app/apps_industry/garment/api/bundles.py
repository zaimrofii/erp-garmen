"""Endpoint **Bundle** MES tambahan (H2.4) — `/api/v1/garmen/bundles/…`.

Melengkapi resource `bundles` yang SUDAH ADA (F2 create via `BundleEngine`, F3
list/detail/schema/aksi, chatter `BundleEvent`) **tanpa mengubah kontrak yang sudah
di-pin**:

  * **sudah ada (tidak disentuh)**: `GET /bundles/` (list 9 key, AllowAny),
    `POST /bundles/` (create F2), `GET /bundles/<id>/` (+`version`,`allowed_actions`),
    `GET …/schema/` (widget QR + chatter), `POST …/<id>/<ACTION>/` (state machine
    `garment.bundle`), `GET /api/v1/chatter/bundles/<id>/`;
  * **baru H2.4**:
      - `GET    /api/v1/garmen/bundles/`  — list **dengan filter** (`search`,`state`,
        `size`,`work_order_id`) + envelope §3 yang sama (baris tetap 9 key);
      - `POST   /api/v1/garmen/bundles/`  — create (size matrix + bundle_size, per WO);
      - `POST   /api/v1/garmen/bundles/preview/` — rencana bundle TANPA menyimpan;
      - `PUT    /api/v1/garmen/bundles/<id>/`    — ubah DRAFT-only + `X-Base-Version`;
      - `DELETE /api/v1/garmen/bundles/<id>/`    — hibrida (DRAFT tanpa jejak produksi);
      - `POST   /api/v1/garmen/bundles/<id>/split/` — pecah bundle (sum qty = sumber);
      - `POST   /api/v1/garmen/bundles/<id>/merge/` — gabung 2+ bundle DRAFT sejenis.

Izin: **tulis = `IsAuthenticated` TANPA role** (keputusan pemilik proyek, konsisten F2 &
simulator); baca tetap `AllowAny` seperti F3. Frontend memakai guard `PRODUCTION_ROLES`.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.actions.executor import resolve_conflict_policy
from apps_industry.garment.api.resources.create_view import _CreateViewMixin
from apps_industry.garment.api.resources.detail_view import serialize_bundle_detail
from apps_industry.garment.api.resources.list_view import ResourceListView, serialize_bundle
from apps_industry.garment.models import Bundle
from apps_industry.garment.services import bundle_services

logger = logging.getLogger(__name__)

__all__ = (
    "BundleDetailCrudView",
    "BundleListCreateView",
    "BundleMergeView",
    "BundlePreviewView",
    "BundleSplitView",
    "serialize_bundle_extra",
)

INDUSTRY = "garmen"
BASE_VERSION_HEADER = "X-Base-Version"
CONFLICT_POLICY_HEADER = "X-Conflict-Policy"
FORCE_HEADER = "X-Force"

#: Batas paging (selaras `list_view.py`).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def serialize_bundle_extra(bundle: Bundle, request=None) -> dict:
    """Detail bundle versi H2.4 (``bundle_detail_row``) — kontrak F3 TETAP utuh.

    ``version`` & ``allowed_actions`` diambil dari jalur yang sama dengan F3
    (`serialize_bundle_detail` + schema builder) supaya klien lama tidak berubah.
    """
    payload = bundle_services.bundle_detail_row(bundle)
    f3 = serialize_bundle_detail(bundle)
    for key, value in f3.items():
        payload.setdefault(key, value)

    return payload


def _error_response(result) -> Response:
    """Peta error service → status (404 tidak ada / 409 konflik / 400 validasi)."""
    if result.not_found:
        code = status.HTTP_404_NOT_FOUND
    elif result.conflict:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST

    return Response({"detail": result.error}, status=code)


def _write_body(result, request, *, status_code: int = status.HTTP_200_OK) -> Response:
    """Respons baris bundle + ringkasan operasi (``ledger_id``/``summary``)."""
    body: dict = {"deleted": result.deleted}
    if result.bundle is not None:
        body = serialize_bundle_extra(result.bundle, request=request)
        body["deleted"] = result.deleted

    body["ledger_id"] = result.ledger_id
    if result.bundles:
        body["bundles"] = [bundle_services.bundle_row(b) for b in result.bundles]
    if result.summary:
        body["summary"] = result.summary

    return Response(body, status=status_code)


class BundleListCreateView(_CreateViewMixin):
    """``GET`` daftar bundle (dengan filter) + ``POST`` create (H2.4).

    ``GET`` **tidak** memakai `ResourceListView` apa adanya karena H2.4 menambah filter
    (`search`/`state`/`size`/`work_order_id`) — tetapi baris & envelope-nya **identik**
    (serializer `serialize_bundle` + key `rows/total_count/has_more/next_cursor/resource/
    industry`) supaya kontrak §3 & konsumen lama (F13/simulator) tidak berubah.
    """

    RESOURCE = "bundles"
    INDUSTRY = "garmen"

    def get(self, request):
        """ListPage §3 + filter opsional (baris tetap 9 key kontrak F3)."""
        limit, error = ResourceListView._int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = ResourceListView._int_param(request, "offset", 0, 0, 100_000)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Bundle.objects.select_related(
            "current_work_center", "production_line", "work_order"
        )
        queryset = self._apply_filters(request, queryset)

        total = queryset.count()
        rows = [serialize_bundle(instance) for instance in queryset[offset : offset + limit]]

        return Response(
            {
                "rows": rows,
                "total_count": total,
                "has_more": offset + len(rows) < total,
                "next_cursor": None,
                "resource": self.RESOURCE,
                "industry": self.INDUSTRY,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _apply_filters(request, queryset):
        """Filter opsional: ``search`` (kode), ``state``, ``size``, ``work_order_id``."""
        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(code__icontains=search)

        state = str(request.query_params.get("state") or "").strip()
        if state:
            queryset = queryset.filter(state__iexact=state)

        size = str(request.query_params.get("size") or "").strip()
        if size:
            queryset = queryset.filter(size__iexact=size)

        work_order_id = str(request.query_params.get("work_order_id") or "").strip()
        if work_order_id:
            parsed = bundle_services._int(work_order_id)
            if parsed is None:
                return queryset.none()
            queryset = queryset.filter(work_order_id=parsed)

        return queryset

    def post(self, request):
        """Buat bundle dari `size_matrix` + `bundle_size` untuk satu WorkOrder."""
        result = bundle_services.create_bundles(request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        body = serialize_bundle_extra(result.bundle, request=request)
        body["created"] = len(result.bundles)
        body["work_order_id"] = result.bundle.work_order_id if result.bundle else None
        body["ledger_id"] = result.ledger_id
        body["summary"] = result.summary
        body["bundles"] = [bundle_services.bundle_row(b) for b in result.bundles]
        body["industry"] = self.INDUSTRY

        return Response(body, status=status.HTTP_201_CREATED)


class BundlePreviewView(APIView):
    """``POST /api/v1/garmen/bundles/preview/`` — rencana bundle TANPA menyimpan."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Kembalikan ``{plan: [...], summary: {...}}`` (dipakai form create H2.4)."""
        result = bundle_services.preview_bundles(request.data or {})
        if result.error:
            return _error_response(result)

        return Response(
            {"plan": result.plan, "summary": result.summary, "industry": INDUSTRY},
            status=status.HTTP_200_OK,
        )


class BundleDetailCrudView(APIView):
    """``GET|PUT|DELETE /api/v1/garmen/bundles/<id>/`` (GET = kontrak F3)."""

    def get_permissions(self):
        """``GET`` tetap AllowAny (perilaku F3); ``PUT``/``DELETE`` wajib login."""
        if self.request.method in ("PUT", "DELETE"):
            return [IsAuthenticated()]
        return []

    @staticmethod
    def _get_bundle(bundle_id: int):
        """Bundle atau ``None`` (→ 404)."""
        return (
            Bundle.objects.select_related(
                "work_order",
                "work_order__order_line",
                "work_order__order_line__order",
                "work_order__order_line__product",
                "current_work_center",
                "production_line",
            )
            .filter(pk=bundle_id)
            .first()
        )

    def get(self, request, bundle_id: int):
        """Detail bundle (payload H2.4 superset; anonim tetap 200 seperti F3)."""
        bundle = self._get_bundle(bundle_id)
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(serialize_bundle_extra(bundle, request=request))

    def put(self, request, bundle_id: int):
        """Ubah bundle (DRAFT-only) + optimistic lock `X-Base-Version` (409 bila basi)."""
        bundle = self._get_bundle(bundle_id)
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        conflict = self._version_conflict(request, bundle)
        if conflict is not None:
            return conflict

        result = bundle_services.update_bundle(bundle, request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request)

    def delete(self, request, bundle_id: int):
        """Hapus bundle (hibrida: DRAFT tanpa jejak produksi; selain itu 409)."""
        bundle = self._get_bundle(bundle_id)
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = bundle_services.delete_bundle(bundle, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request)

    @staticmethod
    def _version_conflict(request, bundle: Bundle):
        """Cek `X-Base-Version` (pola ActionView) → ``Response`` 409 atau ``None``.

        Tanpa header ⇒ tanpa cek konflik (jalur lama tetap jalan). `X-Force: true` /
        `X-Conflict-Policy: last_write_wins` melewati cek.
        """
        base_version = request.headers.get(BASE_VERSION_HEADER)
        if not base_version:
            return None

        policy = resolve_conflict_policy(
            request.headers.get(CONFLICT_POLICY_HEADER),
            request.headers.get(FORCE_HEADER),
        )
        if policy == "last_write_wins":
            return None
        if base_version == bundle.version:
            return None

        return Response(
            {
                "detail": (
                    f"Bundle {bundle.code} sudah berubah sejak dibaca (versi basi); "
                    "muat ulang data lalu ulangi."
                ),
                "current": {
                    "version": bundle.version,
                    "state": bundle.state,
                    "current_work_center": getattr(bundle.current_work_center, "code", None),
                },
            },
            status=status.HTTP_409_CONFLICT,
        )


class BundleSplitView(APIView):
    """``POST /api/v1/garmen/bundles/<id>/split/`` — pecah bundle (DRAFT, tanpa jejak)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id: int):
        """Jalankan split; body = ``{"parts": [qty, qty, ...]}`` (sum = qty sumber)."""
        bundle = BundleDetailCrudView._get_bundle(bundle_id)
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = bundle_services.split_bundle(bundle, request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request, status_code=status.HTTP_201_CREATED)


class BundleMergeView(APIView):
    """``POST /api/v1/garmen/bundles/<id>/merge/`` — gabung bundle DRAFT sejenis ke ``<id>``."""

    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id: int):
        """Body = ``{"bundle_ids": [id, ...]}``; WO/size/SKU wajib sama."""
        bundle = BundleDetailCrudView._get_bundle(bundle_id)
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = bundle_services.merge_bundles(bundle, request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request)
