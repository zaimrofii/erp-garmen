"""Test model ``PrintJob`` (audit cetak) + admin read-only + migrasi terpasang."""

from __future__ import annotations

from django.contrib import admin
from django.db import connection
from django.test import TestCase

from integrations.printing.models import PrintJob


class PrintJobModelTests(TestCase):
    """Skema & default PrintJob (Fase 5)."""

    def make(self, **kwargs) -> PrintJob:
        defaults = {
            "resource": PrintJob.Resource.BUNDLE,
            "resource_id": "1",
            "backend": "mock",
            "ref": "BND-1",
        }
        defaults.update(kwargs)
        return PrintJob.objects.create(**defaults)

    def test_default_status_pending(self):
        job = self.make()

        self.assertEqual(job.status, PrintJob.Status.PENDING)
        self.assertIsNone(job.bytes_sent)
        self.assertEqual(job.last_error, "")
        self.assertIsNotNone(job.created_at)
        self.assertIsNotNone(job.updated_at)

    def test_status_sent_dengan_bytes(self):
        job = self.make(status=PrintJob.Status.SENT, bytes_sent=120)
        job.refresh_from_db()

        self.assertEqual(job.bytes_sent, 120)
        self.assertEqual(job.status, "SENT")

    def test_status_failed_dengan_error(self):
        job = self.make(status=PrintJob.Status.FAILED, last_error="printer offline")
        job.refresh_from_db()

        self.assertIn("offline", job.last_error)

    def test_tidak_ada_unique_constraint(self):
        """Cetak ulang tag yang sama = baris baru (memang diizinkan)."""
        self.make(resource_id="7")
        self.make(resource_id="7")

        self.assertEqual(PrintJob.objects.filter(resource_id="7").count(), 2)

    def test_choices_values(self):
        self.assertEqual(list(PrintJob.Resource.values), ["bundle", "coupon"])
        self.assertEqual(list(PrintJob.Status.values), ["PENDING", "SENT", "FAILED"])

    def test_str_menampilkan_resource_status_backend(self):
        self.assertEqual(str(self.make()), "bundle#1 [PENDING] via mock")

    def test_ordering_terbaru_dulu(self):
        pertama = self.make(resource_id="A")
        kedua = self.make(resource_id="B")

        self.assertEqual(
            list(PrintJob.objects.values_list("id", flat=True)), [kedua.pk, pertama.pk]
        )

    def test_migrasi_terpasang(self):
        """Tabel ``printing_printjob`` ada di DB (0001_initial sudah dijalankan)."""
        self.assertIn(PrintJob._meta.db_table, connection.introspection.table_names())
        self.assertEqual(PrintJob._meta.db_table, "printing_printjob")


class PrintJobAdminTests(TestCase):
    """Admin PrintJob harus terdaftar dan read-only."""

    def test_terdaftar_di_admin(self):
        self.assertIn(PrintJob, admin.site._registry)

    def test_read_only(self):
        model_admin = admin.site._registry[PrintJob]

        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
