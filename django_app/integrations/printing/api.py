"""Endpoint cetak ESC/POS (Fase F).

    POST /api/v1/print/bundle-tag/   {"bundle_id": 42}
    POST /api/v1/print/kupon/        {"ticket_code": "TKT-0001"}   (wajib)

Body bundle-tag memakai **id numerik** (`bundle_id`) karena UI sudah memegang id
dari metadata (`resource.id`), sedangkan kupon memakai `ticket_code` karena kode
itulah yang dicetak & dicek admin (id order line tidak pernah dipegang operator).

Response 200::

    {"ok": true, "resource": "bundle", "resource_id": "42", "bytes": 512,
     "backend": "mock", "print_job_id": 7, "ref": "BND-00042", "status": "SENT"}

Response 400 (bundle/kupon tidak ada, field kosong, atau printer gagal)::

    {"detail": "Bundle dengan id 42 tidak ditemukan."}

Cetak **sengaja tidak** idempotent (mencetak ulang tag yang rusak itu normal),
jadi setiap percobaan = satu baris `PrintJob` (tanpa unique constraint) — lihat
`integrations/printing/models.py`.
"""

from __future__ import annotations

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import Bundle, OrderLine
from integrations.printing.backends import get_backend
from integrations.printing.bundle_tag import BundleTagGenerator
from integrations.printing.coupon import CouponError, CouponGenerator
from integrations.printing.models import PrintJob

logger = logging.getLogger(__name__)

__all__ = ("PrintBundleTagView", "PrintCouponView")


def read_int_field(data: dict, name: str) -> tuple[int | None, str | None]:
    """PURE — baca field angka dari body; return `(value, error_message)`."""
    raw = data.get(name)
    if raw in (None, ""):
        return None, f"Field '{name}' wajib diisi."

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Field '{name}' harus berupa angka."

    if value <= 0:
        return None, f"Field '{name}' harus angka positif."
    return value, None


def read_text_field(data: dict, name: str) -> tuple[str | None, str | None]:
    """PURE — baca field teks wajib dari body; return `(value, error_message)`."""
    raw = data.get(name)
    text = str(raw).strip() if raw is not None else ""
    if text == "":
        return None, f"Field '{name}' wajib diisi."
    return text, None


def send_to_printer(*, resource: str, resource_id, ref: str, payload: bytes) -> Response:
    """Kirim bytes ke backend printer + catat `PrintJob` (selalu satu baris)."""
    backend = get_backend()
    backend_name = str(getattr(backend, "name", "") or "unknown")

    job = PrintJob.objects.create(
        resource=resource,
        resource_id=str(resource_id),
        backend=backend_name,
        ref=ref,
        status=PrintJob.Status.PENDING,
    )

    try:
        result = backend.print_bytes(payload, ref=ref)
    except Exception as exc:  # noqa: BLE001 - backend usb/network boleh melempar
        logger.warning("cetak %s#%s gagal: %s", resource, resource_id, exc)
        return _failed(job, str(exc))

    if not result.ok:
        return _failed(job, result.error or "Printer menolak job cetak.")

    job.status = PrintJob.Status.SENT
    job.bytes_sent = result.bytes_sent
    job.last_error = ""
    job.save(update_fields=["status", "bytes_sent", "last_error", "updated_at"])

    return Response(
        {
            "ok": True,
            "resource": resource,
            "resource_id": str(resource_id),
            "bytes": result.bytes_sent,
            "backend": result.backend or backend_name,
            "print_job_id": job.pk,
            "ref": ref,
            "status": job.status,
        },
        status=status.HTTP_200_OK,
    )


def _failed(job: PrintJob, message: str) -> Response:
    """Tandai job FAILED lalu balas 400 `{"detail": ...}` (kontrak error lain)."""
    job.status = PrintJob.Status.FAILED
    job.last_error = str(message)
    job.save(update_fields=["status", "last_error", "updated_at"])
    return Response({"detail": f"Cetak gagal: {message}"}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    summary="Cetak tag bundle (ESC/POS)",
    description=(
        "Body `{bundle_id}` → render label QR+barcode bundle lalu kirim ke backend "
        "printer (`PRINTER_BACKEND`, default `mock`). Selalu mencatat `PrintJob`; "
        "mencetak ulang = baris baru (tanpa idempotency)."
    ),
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    tags=["printing"],
)
class PrintBundleTagView(APIView):
    """`POST /api/v1/print/bundle-tag/` — cetak label QR + barcode satu bundle."""

    permission_classes = [AllowAny]  # auth menyusul Fase G

    def post(self, request):
        bundle_id, error = read_int_field(request.data or {}, "bundle_id")
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        bundle = (
            Bundle.objects.select_related("work_order", "current_work_center")
            .filter(pk=bundle_id)
            .first()
        )
        if bundle is None:
            return Response(
                {"detail": f"Bundle dengan id {bundle_id} tidak ditemukan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = BundleTagGenerator(bundle).render()
        return send_to_printer(
            resource=PrintJob.Resource.BUNDLE,
            resource_id=bundle.pk,
            ref=str(bundle.code),
            payload=payload,
        )


@extend_schema(
    summary="Cetak kupon piece-rate (ESC/POS)",
    description=(
        "Body `{ticket_code}` (wajib, harus ada di `OrderLine`). Kupon tanpa kode "
        "identitas dilarang → 400. Response sama seperti bundle-tag."
    ),
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    tags=["printing"],
)
class PrintCouponView(APIView):
    """`POST /api/v1/print/kupon/` — cetak kupon piece-rate dari `ticket_code`."""

    permission_classes = [AllowAny]  # auth menyusul Fase G

    def post(self, request):
        ticket_code, error = read_text_field(request.data or {}, "ticket_code")
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        order_line = (
            OrderLine.objects.select_related("order", "product")
            .filter(ticket_code=ticket_code)
            .first()
        )
        if order_line is None:
            return Response(
                {
                    "detail": (
                        f"Order line dengan ticket_code '{ticket_code}' tidak ditemukan."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = CouponGenerator(order_line).render()
        except CouponError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return send_to_printer(
            resource=PrintJob.Resource.COUPON,
            resource_id=order_line.pk,
            ref=str(ticket_code),
            payload=payload,
        )
