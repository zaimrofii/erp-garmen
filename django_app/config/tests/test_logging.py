"""Test formatter log JSON + filter request id (Fase 6)."""

from __future__ import annotations

import json
import logging

from django.test import SimpleTestCase

from config.logging import JsonFormatter
from config.middleware import RequestIDFilter, set_request_id


def make_record(**kwargs) -> logging.LogRecord:
    """Bangun LogRecord manual (tanpa handler) untuk diuji formatter-nya."""
    record = logging.LogRecord(
        name=kwargs.pop("name", "garmen.test"),
        level=kwargs.pop("level", logging.INFO),
        pathname=__file__,
        lineno=10,
        msg=kwargs.pop("msg", "pesan uji"),
        args=kwargs.pop("args", ()),
        exc_info=kwargs.pop("exc_info", None),
        func=kwargs.pop("func", "make_record"),
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


class JsonFormatterTests(SimpleTestCase):
    """Satu record -> satu baris JSON dengan field yang dijanjikan."""

    def setUp(self):
        self.formatter = JsonFormatter()

    def parse(self, record: logging.LogRecord) -> dict:
        return json.loads(self.formatter.format(record))

    def test_field_wajib_selalu_ada(self):
        payload = self.parse(make_record())

        self.assertEqual(
            set(payload),
            {"timestamp", "level", "logger", "message", "module", "funcName"},
        )
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "garmen.test")
        self.assertEqual(payload["message"], "pesan uji")
        self.assertEqual(payload["module"], "test_logging")
        self.assertTrue(payload["funcName"])
        self.assertTrue(payload["timestamp"])

    def test_args_dirender_ke_message(self):
        payload = self.parse(make_record(msg="qty %s ref %s", args=(10, "WO-1")))

        self.assertEqual(payload["message"], "qty 10 ref WO-1")

    def test_request_id_ikut_kalau_ada(self):
        payload = self.parse(make_record(request_id="rid-9"))

        self.assertEqual(payload["request_id"], "rid-9")

    def test_request_id_tidak_muncul_kalau_kosong(self):
        self.assertNotIn("request_id", self.parse(make_record()))

    def test_atribut_non_standar_masuk_extra(self):
        payload = self.parse(make_record(status_code=500, durasi_ms=12))

        self.assertEqual(payload["extra"], {"status_code": 500, "durasi_ms": 12})

    def test_tanpa_atribut_non_standar_tidak_ada_extra(self):
        self.assertNotIn("extra", self.parse(make_record()))

    def test_exc_info_ditulis_di_dalam_json(self):
        try:
            raise ValueError("boom rahasia")
        except ValueError:
            import sys

            payload = self.parse(make_record(msg="gagal", exc_info=sys.exc_info()))

        self.assertIn("ValueError: boom rahasia", payload["exc_info"])

    def test_objek_non_json_tidak_membuat_formatter_gagal(self):
        class Aneh:
            def __str__(self) -> str:
                return "aneh"

        payload = self.parse(make_record(objek=Aneh()))

        self.assertEqual(payload["extra"]["objek"], "aneh")

    def test_hasil_satu_baris(self):
        self.assertNotIn("\n", self.formatter.format(make_record()))


class RequestIDFilterTests(SimpleTestCase):
    """Filter menyalin request id aktif ke record (tanpa menimpa yang sudah ada)."""

    def tearDown(self):
        set_request_id(None)

    def test_request_id_diisi_dari_context_thread(self):
        set_request_id("rid-thread")
        record = make_record()

        self.assertTrue(RequestIDFilter().filter(record))
        self.assertEqual(record.request_id, "rid-thread")

    def test_request_id_record_tidak_ditimpa(self):
        set_request_id("rid-thread")
        record = make_record(request_id="rid-record")

        RequestIDFilter().filter(record)

        self.assertEqual(record.request_id, "rid-record")

    def test_tanpa_context_request_id_tetap_none(self):
        set_request_id(None)
        record = make_record()

        RequestIDFilter().filter(record)

        self.assertIsNone(record.request_id)
