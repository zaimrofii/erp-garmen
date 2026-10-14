"""Test endpoint settings users (F5.4.1 / B26).

Cakupan: `GET|POST /api/v1/settings/users/` + `PUT|DELETE /api/v1/settings/users/<id>/`.

Model: ``core_auth.User`` (AbstractUser + FK ``role``). Catatan kontrak:

  * ``full_name`` = **derived** (``first_name + last_name``), bukan kolom;
  * ``role`` = ``Role.code`` (**UPPERCASE** hasil migrasi ``core_auth.0002``);
  * password selalu lewat ``create_user``/``set_password`` (tidak pernah mentah);
  * **DELETE = soft delete** (``is_active=False``) — user tidak dihapus supaya
    jejak audit & relasi (PROTECT) tetap utuh;
  * endpoint butuh **admin/owner** (superuser dihitung admin).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_settings_users.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import Role, User

USERS_URL = "/api/v1/settings/users/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "username",
    "email",
    "full_name",
    "role",
    # F6.3 — kolom "Kode Operator" (4/6 digit untuk OPERATOR/QC, null untuk role lain).
    "operator_code",
    "is_active",
    "is_staff",
    "last_login",
    "date_joined",
}


def detail_url(pk: int) -> str:
    """URL detail user."""
    return f"{USERS_URL}{pk}/"


class SettingsUsersTests(TestCase):
    """GET/POST/PUT/DELETE + permission admin/owner."""

    @classmethod
    def setUpTestData(cls):
        """3 user: admin (role ADMIN), operator1 (OPERATOR), bekas (nonaktif)."""
        # Role ADMIN/OPERATOR sudah di-seed migrasi `core_auth.0002` → ambil, bukan create.
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.admin = User.objects.create_user(
            username="admin",
            email="admin@klien.com",
            password="rahasia123",
            role=cls.admin_role,
        )
        cls.operator = User.objects.create_user(
            username="operator1",
            email="op1@klien.com",
            password="rahasia123",
            first_name="Operator",
            last_name="Satu",
            role=cls.operator_role,
        )
        cls.inactive = User.objects.create_user(
            username="bekas",
            email="bekas@klien.com",
            password="rahasia123",
            role=cls.operator_role,
            is_active=False,
        )

    def setUp(self):
        """Klien admin (utama) + klien operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ GET
    def test_get_shape_listpage(self):
        """Bentuk ListPage + field baris sesuai kontrak B26."""
        response = self.api.get(USERS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

        row = next(item for item in body["rows"] if item["username"] == "operator1")
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["full_name"], "Operator Satu")
        self.assertEqual(row["role"], "OPERATOR")
        self.assertTrue(row["is_active"])
        self.assertIsNone(row["last_login"])
        self.assertIn("T", row["date_joined"])

    def test_get_anonim_403(self):
        """Tanpa login → 403."""
        self.assertEqual(APIClient().get(USERS_URL).status_code, 403)

    def test_get_non_admin_403(self):
        """Role OPERATOR tidak boleh melihat daftar user."""
        self.assertEqual(self.operator_api.get(USERS_URL).status_code, 403)

    def test_get_kosong(self):
        """DB tanpa user → 200, rows kosong, total_count 0."""
        User.objects.all().delete()

        body = self.api.get(USERS_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_get_dua_user_aktif(self):
        """Filter `?is_active=true` → hanya user aktif (urut username)."""
        body = self.api.get(f"{USERS_URL}?is_active=true").json()

        self.assertEqual([row["username"] for row in body["rows"]], ["admin", "operator1"])
        self.assertEqual(body["total_count"], 2)

    def test_get_search_q_match_email_dan_nama(self):
        """`?q` mencari di username/email/first_name/last_name (icontains)."""
        by_email = self.api.get(f"{USERS_URL}?q=op1@").json()
        by_name = self.api.get(f"{USERS_URL}?q=satu").json()

        self.assertEqual([row["username"] for row in by_email["rows"]], ["operator1"])
        self.assertEqual([row["username"] for row in by_name["rows"]], ["operator1"])

    def test_get_filter_role(self):
        """`?role` case-insensitive terhadap `Role.code`."""
        operator_rows = self.api.get(f"{USERS_URL}?role=operator").json()
        admin_rows = self.api.get(f"{USERS_URL}?role=ADMIN").json()

        self.assertEqual(
            sorted(row["username"] for row in operator_rows["rows"]),
            ["bekas", "operator1"],
        )
        self.assertEqual([row["username"] for row in admin_rows["rows"]], ["admin"])

    def test_get_filter_is_active_false(self):
        """`?is_active=false` → hanya user nonaktif."""
        body = self.api.get(f"{USERS_URL}?is_active=false").json()

        self.assertEqual([row["username"] for row in body["rows"]], ["bekas"])

    # ----------------------------------------------------------------- POST
    def test_post_create_user_201(self):
        """POST membuat user (password di-hash) → 201."""
        response = self.api.post(
            USERS_URL,
            {
                "username": "qc1",
                "email": "qc1@klien.com",
                "password": "rahasia123",
                "first_name": "Dewi",
                "last_name": "Lestari",
                "role_code": "operator",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["username"], "qc1")
        self.assertEqual(body["full_name"], "Dewi Lestari")
        self.assertEqual(body["role"], "OPERATOR")
        self.assertTrue(body["is_active"])

        created = User.objects.get(username="qc1")
        self.assertNotEqual(created.password, "rahasia123")
        self.assertTrue(created.check_password("rahasia123"))

    def test_post_username_duplikat_400(self):
        """Username yang sudah dipakai → 400 (case-insensitive)."""
        response = self.api.post(
            USERS_URL,
            {
                "username": "Operator1",
                "email": "baru@klien.com",
                "password": "rahasia123",
                "role_code": "OPERATOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])

    def test_post_password_pendek_400(self):
        """Password < 8 karakter → 400, user tidak dibuat."""
        response = self.api.post(
            USERS_URL,
            {
                "username": "pendek",
                "email": "pendek@klien.com",
                "password": "pendek",
                "role_code": "OPERATOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="pendek").exists())

    def test_post_role_tidak_dikenal_400(self):
        """`role_code` yang tidak ada → 400."""
        response = self.api.post(
            USERS_URL,
            {
                "username": "x1",
                "email": "x1@klien.com",
                "password": "rahasia123",
                "role_code": "SABLON_LEAD",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    def test_post_email_tidak_valid_400(self):
        """Format email salah → 400."""
        response = self.api.post(
            USERS_URL,
            {
                "username": "x2",
                "email": "bukan-email",
                "password": "rahasia123",
                "role_code": "OPERATOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak valid", response.json()["detail"])

    def test_post_non_admin_403(self):
        """Role OPERATOR tidak boleh membuat user."""
        response = self.operator_api.post(
            USERS_URL,
            {
                "username": "x3",
                "email": "x3@klien.com",
                "password": "rahasia123",
                "role_code": "OPERATOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="x3").exists())

    def test_post_anonim_403(self):
        """Tanpa login → 403 (tidak ada user baru)."""
        response = APIClient().post(
            USERS_URL,
            {
                "username": "x4",
                "email": "x4@klien.com",
                "password": "rahasia123",
                "role_code": "OPERATOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="x4").exists())

    # ------------------------------------------------------------- PUT/DELETE
    def test_put_update_user_200(self):
        """PUT mengubah field; password kosong = tidak diubah, role tetap."""
        response = self.api.put(
            detail_url(self.operator.pk),
            {
                "username": "operator1",
                "email": "op1-baru@klien.com",
                "last_name": "Satu Baru",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["email"], "op1-baru@klien.com")
        self.assertEqual(body["full_name"], "Operator Satu Baru")
        self.assertEqual(body["role"], "OPERATOR")

        self.operator.refresh_from_db()
        self.assertEqual(self.operator.email, "op1-baru@klien.com")
        self.assertTrue(self.operator.check_password("rahasia123"))

    def test_put_dengan_password_baru(self):
        """PUT dengan `password` baru → password di-hash ulang."""
        response = self.api.put(
            detail_url(self.operator.pk),
            {
                "username": "operator1",
                "email": "op1@klien.com",
                "password": "rahasia456",
                "role_code": "ADMIN",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password("rahasia456"))
        self.assertFalse(self.operator.check_password("rahasia123"))
        self.assertEqual(self.operator.role.code, "ADMIN")

    def test_put_user_tidak_ada_404(self):
        """User tidak ditemukan → 404."""
        response = self.api.put(
            detail_url(999999),
            {"username": "ghost", "email": "ghost@klien.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_delete_soft_delete_204(self):
        """DELETE hanya menonaktifkan (`is_active=False`), baris tetap ada."""
        response = self.api.delete(detail_url(self.operator.pk))

        self.assertEqual(response.status_code, 204)
        self.assertTrue(User.objects.filter(pk=self.operator.pk).exists())

        self.operator.refresh_from_db()
        self.assertFalse(self.operator.is_active)

    def test_delete_user_tidak_ada_404(self):
        """User tidak ditemukan → 404."""
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    def test_delete_non_admin_403(self):
        """Role OPERATOR tidak boleh menonaktifkan user."""
        response = self.operator_api.delete(detail_url(self.admin.pk))

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
