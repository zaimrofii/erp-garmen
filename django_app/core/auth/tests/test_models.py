"""Test minimal app `core.auth`: seeding role + relasi User -> Role.

CATATAN: test ini baru bisa jalan setelah `AUTH_USER_MODEL = "core_auth.User"`
di `config/settings.py` dan migration `core_auth` dibuat (lihat Sprint 1.1).
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.db.models import ProtectedError
from django.test import TestCase

from core.auth.models import Role, User


class RoleModelTests(TestCase):
    """Role = data di DB (bukan enum di kode)."""

    def test_role_bawaan_ter_seed(self):
        # Migration 0002_seed_default_roles membuat 5 role bawaan.
        codes = set(Role.objects.values_list("code", flat=True))
        self.assertTrue({pilihan.value for pilihan in Role.Code} <= codes)

    def test_role_baru_bisa_ditambah_tanpa_ubah_kode(self):
        role = Role.objects.create(code="SABLON_LEAD", name="Leader Sablon")
        self.assertEqual(str(role), "SABLON_LEAD - Leader Sablon")
        self.assertTrue(role.is_active)


class UserRoleTests(TestCase):
    """User custom: AbstractUser apa adanya + FK role."""

    def setUp(self):
        self.role_operator = Role.objects.get(code=Role.Code.OPERATOR)

    def test_auth_user_model_menunjuk_ke_core_auth(self):
        self.assertIs(get_user_model(), User)
        self.assertEqual(User._meta.label, "core_auth.User")

    def test_default_role_null(self):
        user = User.objects.create_user(username="operator1", password="rahasia123")
        self.assertIsNone(user.role)

    def test_user_dengan_role(self):
        user = User.objects.create_user(
            username="qc1",
            password="rahasia123",
            role=self.role_operator,
        )
        self.assertEqual(user.role, self.role_operator)
        self.assertIn(user, self.role_operator.users.all())

    def test_role_yang_dipakai_tidak_bisa_dihapus(self):
        User.objects.create_user(
            username="operator2",
            password="rahasia123",
            role=self.role_operator,
        )
        with self.assertRaises(ProtectedError):
            self.role_operator.delete()

    def test_login_bawaan_django_tidak_diubah(self):
        User.objects.create_user(username="admin1", password="rahasia123")
        self.assertIsNotNone(authenticate(username="admin1", password="rahasia123"))
        self.assertIsNone(authenticate(username="admin1", password="salah"))
