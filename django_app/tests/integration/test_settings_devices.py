"""Test endpoint settings devices (F5.4.1 / B28) — `GET /api/v1/settings/devices/`.

Model: ``core.device_profile.DeviceProfile`` (``code`` slug unik, ``name``,
``description``, ``is_active``, ``config``) + ``DeviceBinding`` (``wc_code``,
``last_seen_at``).

Keputusan mapping F5.4.1 (deviasi dari draft spec, disetujui saat recon):

  * endpoint = **katalog profil** (bukan daftar binding) — ``DeviceProfile``
    tidak punya ``device_type``/``wc_code``/``last_seen_at``;
  * ``device_type`` ← ``DeviceProfile.code``; ``label`` ← ``DeviceProfile.name``;
    ``active`` ← ``is_active``; ``config`` ← ``config`` (apa adanya);
  * ``binding_count`` **aditif** = jumlah ``DeviceBinding`` profil tsb;
  * ``wc_code`` & ``last_seen_at`` **tidak** ada di baris; ``?wc_code=`` tetap
    diterima sebagai filter bantu (profil yang punya ≥1 binding di WC itu);
  * read-only → POST/PUT/DELETE **405**; admin/owner saja → non-admin **403**.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_settings_devices.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import Role, User
from core.device_profile.models import DeviceBinding, DeviceProfile

DEVICES_URL = "/api/v1/settings/devices/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"id", "device_type", "label", "description", "active", "config", "binding_count"}


class SettingsDevicesTests(TestCase):
    """Shape katalog profil, filter, dan batas permission B28."""

    @classmethod
    def setUpTestData(cls):
        """5 profil bawaan (seed migrasi) + 1 profil nonaktif + 2 binding OPERATOR_HP."""
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

        # 5 profil bawaan sudah di-seed migrasi `0002`/`0003` → ambil, bukan create.
        cls.hp = DeviceProfile.objects.get(code="OPERATOR_HP")
        cls.kiosk = DeviceProfile.objects.get(code="KIOSK_TABLET")
        # Profil NONAKTIF khusus uji filter (kode baru supaya tidak bentrok seed).
        cls.inactive = DeviceProfile.objects.create(
            code="TABLET_GUDANG", name="Tablet Gudang", is_active=False
        )

        DeviceBinding.objects.create(
            wc_code="SEW-01", device_profile=cls.hp, cookie_token="token-sew-01"
        )
        DeviceBinding.objects.create(
            wc_code="SEW-02", device_profile=cls.hp, cookie_token="token-sew-02"
        )

    def setUp(self):
        """Klien admin (utama) + klien operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    def test_shape_listpage(self):
        """Bentuk ListPage + pemetaan field katalog profil."""
        response = self.api.get(DEVICES_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], DeviceProfile.objects.count())

        row = next(item for item in body["rows"] if item["device_type"] == "OPERATOR_HP")
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["label"], self.hp.name)  # label = DeviceProfile.name
        self.assertEqual(row["description"], self.hp.description)
        self.assertTrue(row["active"])  # active = is_active
        self.assertEqual(row["config"], self.hp.config)
        self.assertEqual(row["binding_count"], 2)

    def test_anonim_403(self):
        """Tanpa login → 403."""
        self.assertEqual(APIClient().get(DEVICES_URL).status_code, 403)

    def test_non_admin_403(self):
        """Role OPERATOR tidak boleh melihat katalog device."""
        self.assertEqual(self.operator_api.get(DEVICES_URL).status_code, 403)

    def test_kosong(self):
        """Belum ada profil → rows kosong (bukan error)."""
        DeviceBinding.objects.all().delete()
        DeviceProfile.objects.all().delete()

        body = self.api.get(DEVICES_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_filter_device_type(self):
        """``?device_type=`` case-insensitive → satu profil + binding_count benar."""
        body = self.api.get(f"{DEVICES_URL}?device_type=operator_hp").json()

        self.assertEqual([row["device_type"] for row in body["rows"]], ["OPERATOR_HP"])
        self.assertEqual(body["rows"][0]["binding_count"], 2)

    def test_filter_wc_code_binding(self):
        """``?wc_code=`` memfilter profil yang punya binding di WC itu."""
        sew01 = self.api.get(f"{DEVICES_URL}?wc_code=SEW-01").json()
        kosong = self.api.get(f"{DEVICES_URL}?wc_code=CUT-99").json()

        self.assertEqual([row["device_type"] for row in sew01["rows"]], ["OPERATOR_HP"])
        self.assertEqual(kosong["rows"], [])

    def test_filter_active_false(self):
        """``?active=false`` → hanya profil nonaktif."""
        body = self.api.get(f"{DEVICES_URL}?active=false").json()

        self.assertEqual([row["device_type"] for row in body["rows"]], ["TABLET_GUDANG"])

    def test_post_405_read_only(self):
        """Endpoint monitoring read-only → POST 405."""
        response = self.api.post(
            DEVICES_URL, {"code": "TABLET_BARU", "name": "Tablet Baru"}, format="json"
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(DeviceProfile.objects.filter(code="TABLET_BARU").exists())
