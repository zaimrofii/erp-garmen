"""Test kolom `operator_code` lewat endpoint B26 (F6.3 — Opsi B, TANPA endpoint baru).

Cakupan:

  * ``GET /api/v1/settings/users/`` mengirim ``operator_code`` (4/6 digit untuk
    OPERATOR/QC, ``null`` untuk role lain);
  * **regenerate** = ``PUT /api/v1/settings/users/<id>/`` dengan ``operator_code: ""``
    → backend mengundi kode baru (memakai `User.save()` F6.1, bukan endpoint baru);
  * kode eksplisit 4/6 digit diterima; format salah / role salah / kode duplikat → 400;
  * permission tetap admin/owner.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_user_operator_code_api.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import Role, User

USERS_URL = "/api/v1/settings/users/"


def detail_url(pk: int) -> str:
    """URL detail user (PUT/DELETE)."""
    return f"{USERS_URL}{pk}/"


class OperatorCodeApiTests(TestCase):
    """`operator_code` di endpoint settings users (B26 + F6.3)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.supervisor_role = Role.objects.get(code=Role.Code.SUPERVISOR)

        cls.admin = User.objects.create_user(
            username="admin-f63", email="admin-f63@klien.com", password="rahasia123",
            role=cls.admin_role,
        )
        cls.operator = User.objects.create_user(
            username="operator-f63", email="op-f63@klien.com", password="rahasia123",
            first_name="Operator", last_name="F63", role=cls.operator_role,
        )
        cls.operator2 = User.objects.create_user(
            username="operator2-f63", email="op2-f63@klien.com", password="rahasia123",
            role=cls.operator_role,
        )
        cls.supervisor = User.objects.create_user(
            username="spv-f63", email="spv-f63@klien.com", password="rahasia123",
            role=cls.supervisor_role,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def put_user(self, pk: int, **extra):
        """PUT detail user dengan field wajib (username/email) + `extra`."""
        user = User.objects.get(pk=pk)
        body = {
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
        }
        body.update(extra)

        return self.api.put(detail_url(pk), body, format="json")

    # ------------------------------------------------------------------ GET
    def test_list_mengirim_operator_code(self):
        """OPERATOR → kode 4 digit; ADMIN → null (invariant F6.1)."""
        body = self.api.get(USERS_URL).json()
        rows = {row["username"]: row for row in body["rows"]}

        self.assertRegex(rows["operator-f63"]["operator_code"], r"^\d{4}$")
        self.assertIsNone(rows["admin-f63"]["operator_code"])
        self.assertIsNone(rows["spv-f63"]["operator_code"])

    # ----------------------------------------------------------------- PUT
    def test_put_kode_kosong_regenerate_kode_baru(self):
        """`operator_code: ""` → kode baru (bukan endpoint baru; diundi `User.save()`)."""
        before = self.operator.operator_code
        self.assertIsNotNone(before)

        response = self.put_user(self.operator.pk, operator_code="")

        self.assertEqual(response.status_code, 200)
        after = response.json()["operator_code"]
        self.assertRegex(after, r"^\d{4}$")
        self.assertNotEqual(after, before)

        self.operator.refresh_from_db()
        self.assertEqual(self.operator.operator_code, after)

    def test_put_kode_eksplisit_disimpan(self):
        """Kode 4 digit eksplisit dipakai apa adanya."""
        response = self.put_user(self.operator.pk, operator_code="7788")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operator_code"], "7788")
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.operator_code, "7788")

    def test_put_kode_format_salah_400(self):
        """Bukan 4/6 digit → 400 dan kode lama tidak berubah."""
        before = self.operator.operator_code

        response = self.put_user(self.operator.pk, operator_code="12")

        self.assertEqual(response.status_code, 400)
        self.assertIn("4 atau 6 digit", response.json()["detail"])
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.operator_code, before)

    def test_put_kode_untuk_role_lain_400(self):
        """SUPERVISOR tidak boleh punya kode operator."""
        response = self.put_user(self.supervisor.pk, operator_code="")

        self.assertEqual(response.status_code, 400)
        self.assertIn("OPERATOR", response.json()["detail"])
        self.supervisor.refresh_from_db()
        self.assertIsNone(self.supervisor.operator_code)

    def test_put_kode_duplikat_400(self):
        """Kode yang sudah dipakai user lain → 400 (bukan IntegrityError)."""
        taken = self.operator2.operator_code

        response = self.put_user(self.operator.pk, operator_code=taken)

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])

    def test_put_kode_bukan_admin_403(self):
        """Operator (non-admin) tidak boleh mengubah kode."""
        api = APIClient()
        api.force_authenticate(self.operator)

        response = api.put(
            detail_url(self.operator2.pk),
            {
                "username": self.operator2.username,
                "email": self.operator2.email,
                "operator_code": "",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
