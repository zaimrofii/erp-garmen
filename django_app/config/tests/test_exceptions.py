"""Test ``custom_exception_handler`` (Fase 6).

Yang dijamin: response bersih (tanpa stack trace) saat ``DEBUG=False``, error DRF
yang dikenal tetap rapi + diberi ``request_id``, dan perilaku dev (``DEBUG=True``)
tidak diubah.
"""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from config.exceptions import INTERNAL_ERROR_DETAIL, custom_exception_handler


class BoomView(APIView):
    """View uji yang melempar exception tak terduga."""

    def get(self, request):
        raise RuntimeError("detail rahasia internal")


class ValidationView(APIView):
    """View uji yang melempar ValidationError."""

    def get(self, request):
        raise ValidationError({"qty": ["Qty wajib diisi."]})


class ExceptionHandlerTests(SimpleTestCase):
    def test_handler_terpasang_di_settings(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["EXCEPTION_HANDLER"],
            "config.exceptions.custom_exception_handler",
        )

    @override_settings(DEBUG=False)
    def test_exception_tak_terduga_jadi_500_tanpa_stack_trace(self):
        request = APIRequestFactory().get("/boom/")
        request.request_id = "rid-boom"

        with self.assertLogs("django.request", level="ERROR") as logs:
            response = BoomView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["detail"], INTERNAL_ERROR_DETAIL)
        self.assertEqual(response.data["request_id"], "rid-boom")
        # Pesan internal TIDAK boleh bocor ke klien...
        self.assertNotIn("rahasia", str(response.data).lower())
        self.assertNotIn("traceback", str(response.data).lower())
        # ...tapi HARUS ada di log (beserta traceback).
        self.assertIn("RuntimeError", logs.output[0])
        self.assertIn("Traceback", logs.output[0])

    @override_settings(DEBUG=False)
    def test_tanpa_request_id_payload_tetap_valid(self):
        request = APIRequestFactory().get("/boom/")

        with self.assertLogs("django.request", level="ERROR"):
            response = BoomView.as_view()(request)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(dict(response.data), {"detail": INTERNAL_ERROR_DETAIL})

    @override_settings(DEBUG=True)
    def test_debug_true_exception_dibiarkan_naik(self):
        request = APIRequestFactory().get("/boom/")

        with self.assertRaisesMessage(RuntimeError, "detail rahasia internal"):
            BoomView.as_view()(request)

    @override_settings(DEBUG=False)
    def test_validation_error_400_rapi_dengan_request_id(self):
        request = APIRequestFactory().get("/validasi/")
        request.request_id = "rid-400"

        response = ValidationView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["qty"], ["Qty wajib diisi."])
        self.assertEqual(response.data["request_id"], "rid-400")

    @override_settings(DEBUG=False)
    def test_api_exception_lain_tetap_rapi(self):
        response = custom_exception_handler(
            NotFound("tidak ada"), {"request": None, "view": None}
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(str(response.data["detail"]), "tidak ada")
        self.assertNotIn("request_id", response.data)
