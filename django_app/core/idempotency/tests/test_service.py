"""Test IdempotencyService (kontrak §5.1): check miss/hit, hash beda, save, cleanup."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.idempotency.models import IdempotencyRecord
from core.idempotency.services import IdempotencyService

RESOURCE = "bundles"
RESOURCE_ID = "1"
ACTION = "BUNDLE_START"
HASH = "a" * 64
OTHER_HASH = "b" * 64


class IdempotencyServiceTests(TestCase):
    """Cek & simpan IdempotencyRecord."""

    def setUp(self):
        self.service = IdempotencyService()

    def test_check_miss_kalau_key_belum_ada(self):
        self.assertIsNone(self.service.check(None, RESOURCE, RESOURCE_ID, ACTION, HASH))
        self.assertIsNone(
            self.service.check("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH)
        )

    def test_check_hit_kalau_semua_cocok(self):
        self.service.save("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {"ok": True})

        record = self.service.check("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH)

        self.assertIsNotNone(record)
        self.assertEqual(record.response_status, 200)
        self.assertEqual(record.response_body, {"ok": True})

    def test_check_none_kalau_request_berbeda(self):
        self.service.save("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {"ok": True})

        self.assertIsNone(
            self.service.check("key-1", RESOURCE, RESOURCE_ID, ACTION, OTHER_HASH)
        )
        self.assertIsNone(
            self.service.check("key-1", RESOURCE, RESOURCE_ID, "BUNDLE_SCRAP", HASH)
        )
        self.assertIsNone(
            self.service.check("key-1", RESOURCE, "99", ACTION, HASH)
        )

    def test_check_none_dan_hapus_record_kedaluwarsa(self):
        record = self.service.save(
            "key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {"ok": True}
        )
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        self.assertIsNone(
            self.service.check("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH)
        )
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_save_membuat_lalu_memperbarui_record_key_sama(self):
        pertama = self.service.save(
            "key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {"ok": True}
        )
        kedua = self.service.save(
            "key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {"ok": False}
        )

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertEqual(kedua.response_body, {"ok": False})
        self.assertIsNotNone(kedua.expires_at)
        self.assertGreater(kedua.expires_at, timezone.now())

    def test_cleanup_expired_hanya_menghapus_yang_kedaluwarsa(self):
        hidup = self.service.save("key-1", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {})
        mati = self.service.save("key-2", RESOURCE, RESOURCE_ID, ACTION, HASH, 200, {})
        IdempotencyRecord.objects.filter(pk=mati.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        deleted = self.service.cleanup_expired()

        self.assertEqual(deleted, 1)
        self.assertEqual(
            list(IdempotencyRecord.objects.values_list("pk", flat=True)), [hidup.pk]
        )
