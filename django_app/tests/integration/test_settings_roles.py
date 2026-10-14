"""Test endpoint settings roles (F5.4.1 / B27) — `GET /api/v1/settings/roles/`.

Model: ``core_auth.Role`` (``code`` unik, ``name``, ``description``, ``is_active``).
Catatan kontrak:

  * ``label`` = **rename** dari ``Role.name`` (model tidak punya kolom ``label``);
  * ``user_count`` = jumlah user ber-role tsb (via ``related_name="users"``);
  * ``permissions`` TIDAK ada di kontrak (hak akses app diatur di klien);
  * read-only: seeding lewat migrasi ``core_auth.0002`` → POST/PUT/DELETE **405**;
  * permission ``IsAuthenticated`` (semua role boleh melihat daftar role).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_settings_roles.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import Role, User

ROLES_URL = "/api/v1/settings/roles/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"id", "code", "label", "description", "is_active", "user_count"}


class SettingsRolesTests(TestCase):
    """Shape, isi, dan batas permission B27."""

    @classmethod
    def setUpTestData(cls):
        """2 role (ADMIN, OPERATOR) + 1 user per role (uji ``user_count``)."""
        # Role bawaan sudah di-seed migrasi `core_auth.0002` (5 role) → ambil, bukan create.
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.admin = User.objects.create_user(
            username="admin", email="admin@klien.com", password="rahasia123",
            role=cls.admin_role,
        )
        cls.operator = User.objects.create_user(
            username="operator1", email="op1@klien.com", password="rahasia123",
            role=cls.operator_role,
        )

    def setUp(self):
        """Klien admin + klien operator (semua role boleh GET)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    def test_shape_listpage(self):
        """Bentuk ListPage + field baris (`label` dari `Role.name`)."""
        response = self.api.get(ROLES_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], Role.objects.count())
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

        row = next(item for item in body["rows"] if item["code"] == "ADMIN")
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["label"], self.admin_role.name)  # label = Role.name
        self.assertEqual(row["description"], self.admin_role.description)
        self.assertTrue(row["is_active"])

    def test_anonim_403(self):
        """Tanpa login → 403."""
        self.assertEqual(APIClient().get(ROLES_URL).status_code, 403)

    def test_kosong(self):
        """Belum ada role (DB bersih) → rows kosong, bukan error."""
        User.objects.all().delete()
        Role.objects.all().delete()

        body = self.api.get(ROLES_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_semua_role_urut_kode(self):
        """Semua role (termasuk seed migrasi) tampil urut ``code``."""
        body = self.api.get(ROLES_URL).json()

        expected = sorted(Role.objects.values_list("code", flat=True))
        self.assertEqual([row["code"] for row in body["rows"]], expected)
        self.assertIn("ADMIN", expected)
        self.assertIn("OPERATOR", expected)

    def test_user_count_benar(self):
        """``user_count`` menghitung user ber-role tsb."""
        User.objects.create_user(
            username="admin2", email="admin2@klien.com", password="rahasia123",
            role=self.admin_role,
        )

        body = self.api.get(ROLES_URL).json()
        counts = {row["code"]: row["user_count"] for row in body["rows"]}

        self.assertEqual(counts["ADMIN"], 2)
        self.assertEqual(counts["OPERATOR"], 1)

    def test_operator_boleh_melihat(self):
        """Role non-admin tetap boleh melihat daftar role (keputusan F5.4.1)."""
        self.assertEqual(self.operator_api.get(ROLES_URL).status_code, 200)

    def test_post_405_read_only(self):
        """Role adalah master data → POST tidak diizinkan (405)."""
        response = self.api.post(
            ROLES_URL, {"code": "SABLON_LEAD", "name": "Lead Sablon"}, format="json"
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Role.objects.filter(code="SABLON_LEAD").exists())

    def test_paging_limit_dan_cursor(self):
        """``?limit`` + ``?cursor`` (offset) bekerja, termasuk halaman terakhir."""
        total = Role.objects.count()
        self.assertGreaterEqual(total, 2)

        first = self.api.get(f"{ROLES_URL}?limit=1").json()
        second = self.api.get(f"{ROLES_URL}?limit=1&cursor=1").json()
        last = self.api.get(f"{ROLES_URL}?limit=1&cursor={total - 1}").json()

        self.assertEqual(len(first["rows"]), 1)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 1)

        self.assertEqual(len(second["rows"]), 1)
        self.assertNotEqual(first["rows"][0]["code"], second["rows"][0]["code"])

        self.assertEqual(len(last["rows"]), 1)
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_cursor"])
