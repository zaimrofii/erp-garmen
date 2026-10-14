"""Test audit trail (Fase 6): ``AuditLogger``, model ``AuditLog``, admin read-only."""

from __future__ import annotations

import uuid

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.audit.models import AuditLog
from core.audit.services import AuditLogger

User = get_user_model()


def make_request(
    *,
    ip: str | None = "10.0.0.5",
    forwarded: str | None = None,
    user_agent: str | None = "agent-test",
    request_id: str | None = "rid-123",
):
    """Request tiruan dengan META ala WSGI (+ request_id ala middleware)."""
    request = RequestFactory().post("/api/v1/example/")
    if ip is not None:
        request.META["REMOTE_ADDR"] = ip
    if forwarded is not None:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded
    if user_agent is not None:
        request.META["HTTP_USER_AGENT"] = user_agent
    if request_id is not None:
        request.request_id = request_id
    return request


class AuditLoggerTests(TestCase):
    """Penulisan AuditLog dari berbagai bentuk input."""

    def setUp(self):
        self.logger = AuditLogger()

    def test_log_minimal(self):
        record = self.logger.log(None, "BUNDLE_START", "bundles", 7)

        self.assertEqual(record.action, "BUNDLE_START")
        self.assertEqual(record.resource, "bundles")
        self.assertEqual(record.resource_id, "7")
        self.assertEqual(record.result, AuditLog.Result.OK)
        self.assertIsNone(record.user)
        self.assertEqual(record.request_id, "")
        self.assertIsNone(record.ip_address)
        self.assertEqual(record.user_agent, "")
        self.assertEqual(record.payload, {})
        self.assertEqual(record.metadata, {})
        self.assertIsNotNone(record.timestamp)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_log_dengan_request_mengisi_ip_user_agent_dan_request_id(self):
        request = make_request()

        record = self.logger.log(
            None, "BUNDLE_START", "bundles", 7, request=request, payload={"qty": 10}
        )

        self.assertEqual(record.ip_address, "10.0.0.5")
        self.assertEqual(record.user_agent, "agent-test")
        self.assertEqual(record.request_id, "rid-123")
        self.assertEqual(record.payload, {"qty": 10})

    def test_x_forwarded_for_dipakai_kalau_ada(self):
        request = make_request(forwarded="203.0.113.9, 10.0.0.1")

        record = self.logger.log(None, "SYNC_WIP", "work_order", "WO-1", request=request)

        self.assertEqual(record.ip_address, "203.0.113.9")

    def test_ip_tidak_valid_diabaikan_tanpa_error(self):
        request = make_request(forwarded="bukan-ip")

        record = self.logger.log(None, "SYNC_WIP", "work_order", "WO-1", request=request)

        self.assertIsNone(record.ip_address)

    def test_user_terautentikasi_di_request_dipakai(self):
        user = User.objects.create_user(username="operator-audit", password="rahasia123")
        request = make_request()
        request.user = user

        record = self.logger.log(None, "BUNDLE_START", "bundles", 7, request=request)

        self.assertEqual(record.user_id, user.pk)

    def test_user_anonim_tidak_dicatat(self):
        request = make_request()
        request.user = AnonymousUser()

        self.assertIsNone(self.logger.log(None, "X", "bundles", 1, request=request).user)

    def test_user_explisit_dipakai_kalau_diberikan(self):
        user = User.objects.create_user(username="qc-audit", password="rahasia123")

        record = self.logger.log(user, "BUNDLE_QC", "bundles", 1)

        self.assertEqual(record.user_id, user.pk)

    def test_result_tidak_dikenal_error(self):
        with self.assertRaisesMessage(ValueError, "result audit tidak dikenal"):
            self.logger.log(None, "X", "bundles", 1, result="NGACO")

    def test_payload_non_json_dibuat_aman(self):
        record = self.logger.log(
            None,
            "X",
            "bundles",
            1,
            payload={"id": uuid.uuid4(), "kapan": timezone.now()},
            metadata={"objek": object()},
        )

        self.assertIsInstance(record.payload["id"], str)
        self.assertIsInstance(record.payload["kapan"], str)
        self.assertIsInstance(record.metadata["objek"], str)

    def test_index_dan_db_index_sesuai_rencana(self):
        fields = {tuple(index.fields) for index in AuditLog._meta.indexes}

        self.assertIn(("resource", "resource_id"), fields)
        self.assertIn(("user", "timestamp"), fields)
        self.assertTrue(AuditLog._meta.get_field("timestamp").db_index)

    def test_str_menampilkan_aksi_resource_dan_result(self):
        record = self.logger.log(None, "SYNC_WIP", "work_order", "WO-1")

        self.assertEqual(str(record), "SYNC_WIP work_order#WO-1 [OK]")

    def test_migrasi_terpasang(self):
        self.assertEqual(AuditLog._meta.db_table, "audit_auditlog")
        self.assertIn(AuditLog._meta.db_table, connection.introspection.table_names())

    def test_choices_result(self):
        self.assertEqual(list(AuditLog.Result.values), ["OK", "FAILED", "CONFLICT", "DENIED"])


class AuditLogAdminTests(TestCase):
    """Admin audit harus read-only."""

    def test_terdaftar_dan_read_only(self):
        self.assertIn(AuditLog, admin.site._registry)
        model_admin = admin.site._registry[AuditLog]

        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
