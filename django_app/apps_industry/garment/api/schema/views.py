"""Endpoint metadata resource (Kontrak §1) — dua bentuk path.

  * ``GET /api/v1/<industry>/<resource>/<id>/schema/`` — metadata satu instance
    (dipakai frontend saat membuka halaman resource tertentu);
  * ``GET /api/v1/metadata/<resource>/`` — metadata tingkat resource (kontrak §3);
    instance default = yang pertama, bisa dioverride ``?id=``.

Keduanya memakai builder yang sama supaya bentuk JSON-nya identik dan header
``X-Schema-Version`` tetap jadi guard kompatibilitas. Fase A: segment ``industry``
divalidasi whitelist (``api/industries.py``) → industri tak dikenal = 404 eksplisit.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.industries import DEFAULT_INDUSTRY, require_industry
from apps_industry.garment.api.schema.builder import SCHEMA_VERSION
from apps_industry.garment.api.schema.registry import get_builder

logger = logging.getLogger(__name__)


def build_metadata_response(builder_class, instance, request, industry: str) -> Response:
    """Rakit response metadata satu instance (JSON + header `X-Schema-Version`)."""
    builder = builder_class(instance=instance, request=request, industry=industry)
    response = Response(builder.build(), status=status.HTTP_200_OK)
    response["X-Schema-Version"] = SCHEMA_VERSION
    return response


def resolve_instance(builder_class, instance_id: int | None = None):
    """Ambil instance resource lewat `MODEL` builder; `None` kalau tak ketemu.

    `instance_id=None` → instance pertama (pk terkecil). Dipakai endpoint metadata
    tingkat resource supaya URL-nya tidak wajib membawa id.
    """
    model = getattr(builder_class, "MODEL", None)
    if model is None:
        logger.error("builder %s belum mendefinisikan MODEL.", builder_class.__name__)
        return None

    queryset = model.objects.all()
    if builder_class.SELECT_RELATED:
        queryset = queryset.select_related(*builder_class.SELECT_RELATED)

    queryset = queryset.order_by("pk")
    if instance_id is None:
        return queryset.first()

    return queryset.filter(pk=instance_id).first()


class SchemaView(APIView):
    """Kirim metadata resource (schema JSON) untuk frontend render halaman."""

    # Metadata bukan data bisnis: perangkat/operator boleh membacanya sebelum
    # login (frontend butuh ini untuk tahu harus render apa). Data bisnisnya
    # sendiri tetap dilindungi endpoint masing-masing di sprint berikutnya.
    permission_classes = [AllowAny]

    def get(self, request, industry: str, resource: str, id: int):
        """Resolve builder dari registry, ambil instance, kembalikan metadata."""
        # Fase A: industri divalidasi dulu (404 eksplisit) — bukan 200 payload salah.
        industry_code = require_industry(industry)

        builder_class = get_builder(resource)
        if builder_class is None:
            logger.info("schema: resource '%s' tidak dikenal.", resource)
            return Response(
                {"detail": f"Resource '{resource}' tidak dikenal."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if getattr(builder_class, "MODEL", None) is None:
            logger.error(
                "schema: builder %s belum mendefinisikan MODEL.", builder_class.__name__
            )
            return Response(
                {"detail": "Resource belum siap (builder tanpa model)."},
                status=status.HTTP_404_NOT_FOUND,
            )

        instance = resolve_instance(builder_class, id)
        if instance is None:
            return Response(
                {"detail": f"Resource '{resource}' dengan id {id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return build_metadata_response(builder_class, instance, request, industry_code)


class MetadataView(APIView):
    """Metadata resource tanpa id di URL: `GET /api/v1/metadata/<resource>/`.

    Query opsional: `?id=<pk>` (default: instance pertama) dan `?industry=<kode>`
    (default `garmen`). Resource tak dikenal / belum punya data → 404.

    Path ini menggantikan "kecelakaan" Fase A: dulu `/api/v1/metadata/bundles/`
    cocok sebagai `industry="metadata"` dan menjawab 200 berisi ListPage.
    """

    permission_classes = [AllowAny]

    def get(self, request, resource: str):
        """Kembalikan metadata yang sama dengan `.../<industry>/<resource>/<id>/schema/`."""
        builder_class = get_builder(resource)
        if builder_class is None:
            logger.info("metadata: resource '%s' tidak dikenal.", resource)
            return Response(
                {"detail": f"Resource '{resource}' tidak dikenal."},
                status=status.HTTP_404_NOT_FOUND,
            )

        industry = require_industry(
            request.query_params.get("industry") or DEFAULT_INDUSTRY
        )

        raw_id = request.query_params.get("id")
        instance_id: int | None = None
        if raw_id not in (None, ""):
            try:
                instance_id = int(raw_id)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'id' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        instance = resolve_instance(builder_class, instance_id)
        if instance is None:
            detail = (
                f"Resource '{resource}' dengan id {instance_id} tidak ditemukan."
                if instance_id is not None
                else f"Belum ada data '{resource}' untuk membangun metadata."
            )
            return Response({"detail": detail}, status=status.HTTP_404_NOT_FOUND)

        return build_metadata_response(builder_class, instance, request, industry)
