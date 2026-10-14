"""Test endpoint sync master manual (`POST /api/v1/sync/master/<entity>/`).

Cakupan:

* **9 entity valid** (1 test per entity) → 200 ``{status: "queued", task_id}``
  + verifikasi ``.delay()`` dipanggil pada **task yang benar** (di-mock);
* entity tak dikenal → **404**;
* method ``GET`` → **405**;
* anonim → **403** (konsekuensi permission ``IsAuthenticated``).

Catatan: endpoint memakai ``IsAuthenticated`` (repo **tidak** punya permission
admin) → test mengirim user terautentikasi lewat ``force_authenticate``.
Patch dilakukan pada ``<task>.delay`` (bukan nama di modul api) karena
``MASTER_TASKS`` mengikat objek task saat import — pola sama dengan
``test_sync_endpoint.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import User

URL = "/api/v1/sync/master/{entity}/"

#: entity -> dotted path `.delay` task Celery-nya (task di-import di api.py).
DELAY_TARGET = {
    "products": "integrations.erp_sync.api.sync_master_products.delay",
    "boms": "integrations.erp_sync.api.sync_master_boms.delay",
    "partners": "integrations.erp_sync.api.sync_master_partners.delay",
    "locations": "integrations.erp_sync.api.sync_master_locations.delay",
    "taxes": "integrations.erp_sync.api.sync_master_taxes.delay",
    "uoms": "integrations.erp_sync.api.sync_master_uoms.delay",
    "warehouses": "integrations.erp_sync.api.sync_master_warehouses.delay",
    "journals": "integrations.erp_sync.api.sync_master_journals.delay",
    "currencies": "integrations.erp_sync.api.sync_master_currencies.delay",
}


class SyncMasterViewTests(TestCase):
    """`POST /api/v1/sync/master/<entity>/` — enqueue task master sync."""

    def setUp(self):
        self.api = APIClient()
        self.user = User.objects.create_user(
            username="admin-master", password="rahasia"  # noqa: S106 - kredensial test
        )
        self.api.force_authenticate(user=self.user)

    # ------------------------------------------------------------------ helper
    def _assert_queued(self, entity: str) -> None:
        """POST 1 entity valid; pastikan 200 + `.delay()` task entity itu dipanggil."""
        with patch(
            DELAY_TARGET[entity], return_value=SimpleNamespace(id=f"task-{entity}")
        ) as delay:
            response = self.api.post(URL.format(entity=entity))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "queued", "task_id": f"task-{entity}"}
        )
        delay.assert_called_once_with()

    # ------------------------------------------------------- 9 entity valid
    def test_products_queued(self):
        self._assert_queued("products")

    def test_boms_queued(self):
        self._assert_queued("boms")

    def test_partners_queued(self):
        self._assert_queued("partners")

    def test_locations_queued(self):
        self._assert_queued("locations")

    def test_taxes_queued(self):
        self._assert_queued("taxes")

    def test_uoms_queued(self):
        self._assert_queued("uoms")

    def test_warehouses_queued(self):
        self._assert_queued("warehouses")

    def test_journals_queued(self):
        self._assert_queued("journals")

    def test_currencies_queued(self):
        self._assert_queued("currencies")

    # ------------------------------------------------------------ edge cases
    def test_entity_tidak_dikenal_404(self):
        response = self.api.post(URL.format(entity="tidak-ada"))

        self.assertEqual(response.status_code, 404)

    def test_method_get_405(self):
        response = self.api.get(URL.format(entity="products"))

        self.assertEqual(response.status_code, 405)

    def test_anonim_403_butuh_login(self):
        response = APIClient().post(URL.format(entity="products"))

        self.assertEqual(response.status_code, 403)
