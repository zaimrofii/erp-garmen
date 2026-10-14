"""I8.10 — fail-safe **end-to-end**: ERP tidak tersedia, MES tetap jalan.

Berbeda dari ``test_odoo_adapter_failsafe.py`` (menguji **adapter** saja), test
ini menguji **rantai penuh**: ``SyncRecord`` → task Celery (``.apply()``) →
adapter → ``SyncRecord``. Adapter disetel ``null`` (``ERP_ADAPTER="null"``)
sehingga tidak ada jaringan/Odoo sama sekali; yang dibuktikan:

* ``get_adapter()`` → :class:`NullAdapter` (juga saat nama vendor tak dikenal);
* 4 task push — WIP, FG (``tasks.py``), SCRAP (``tasks_scrap.py``), INVOICE
  (``tasks_invoice.py``) — dijalankan ``.apply()`` **tanpa exception** →
  ``SyncRecord`` ``SENT`` dengan ``erp_id`` ``NULL-<uuid>``;
* MES tidak terganggu: aksi bundle sungguhan tetap **200** dan ``BundleEvent``
  tetap tercatat setelah seluruh push dijalankan.

Catatan temuan saat menulis test ini: ``NullAdapter`` semula **tidak** punya
``push_scrap_wo``/``push_customer_invoice_wo`` (kontrak tambahan I4/I5 yang hanya
ada di ``OdooAdapter``) sehingga ``ERP_ADAPTER=null`` melempar ``AttributeError``
dan task scrap/invoice selalu FAILED — method no-op-nya ditambahkan di
``adapters/null.py`` (implementasi bisnis ``OdooAdapter`` tidak disentuh).
"""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_scrap_accumulator,
    make_work_order,
)
from core.auth.models import User
from integrations.erp_sync.adapters.factory import get_adapter
from integrations.erp_sync.adapters.null import NullAdapter
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncStage, SyncStatus
from integrations.erp_sync.services.invoice_sync import InvoiceSyncService
from integrations.erp_sync.tasks import push_fg_receipt, push_wip_issue
from integrations.erp_sync.tasks_invoice import sync_invoice
from integrations.erp_sync.tasks_scrap import sync_scrap_accumulator
from master.models import Product

WIP_PAYLOAD = {"ref": "WO-FS-1", "qty": 5}
FG_PAYLOAD = {"ref": "WO-FS-2", "qty": 5}


@override_settings(ERP_ADAPTER="null", ODOO_UOM_ID=33)
class FailSafeFullStackTests(TestCase):
    """Seluruh push ke ERP memakai ``NullAdapter`` — MES tetap jalan."""

    # ------------------------------------------------------------------ adapter
    def test_get_adapter_fail_safe_ke_null(self):
        self.assertIsInstance(get_adapter(), NullAdapter)
        # Vendor tak dikenal → fallback NullAdapter (bukan exception).
        self.assertIsInstance(get_adapter("vendor-ngawur"), NullAdapter)

    # -------------------------------------------------------------------- push
    def test_empat_task_push_sent_dengan_erp_id_null(self):
        sync = SyncIdempotency()
        wip = sync.get_or_create_sync_record(
            "work_order", "WO-FS-1", SyncStage.WIP, WIP_PAYLOAD
        )
        fg = sync.get_or_create_sync_record(
            "work_order", "WO-FS-2", SyncStage.FG, FG_PAYLOAD
        )

        product = Product.objects.create(
            code="TS-FS-SCRAP", name="Kaos FS", odoo_id=902
        )
        bundle = make_bundle(
            work_order=make_work_order(order_line=make_order_line(product=product))
        )
        accumulator = make_scrap_accumulator(bundle=bundle, qty=2)
        order = make_order(code="ORD-FS-1")
        InvoiceSyncService().enqueue(order)

        # Tidak ada satu pun yang melempar ke pemanggil (.apply().get()).
        results = {
            "wip": push_wip_issue.apply(
                args=("work_order", "WO-FS-1", WIP_PAYLOAD, wip.pk)
            ).get(),
            "fg": push_fg_receipt.apply(
                args=("work_order", "WO-FS-2", FG_PAYLOAD, fg.pk)
            ).get(),
            "scrap": sync_scrap_accumulator.apply().get(),
            "invoice": sync_invoice.apply().get(),
        }

        self.assertEqual(results["wip"]["status"], "sent")
        self.assertEqual(results["fg"]["status"], "sent")
        self.assertEqual(results["scrap"]["sent"], 1)
        self.assertEqual(results["invoice"]["sent"], 1)

        # Tiap push menyimpan erp_id NullAdapter (NULL-<uuid>) di SyncRecord.
        for record in (
            wip,
            fg,
            SyncRecord.objects.get(
                resource="scrap_accumulator",
                resource_id=str(accumulator.pk),
                stage=SyncStage.SCRAP,
            ),
            SyncRecord.objects.get(
                resource="order", resource_id=str(order.pk), stage=SyncStage.INVOICE
            ),
        ):
            record.refresh_from_db()
            self.assertEqual(record.status, SyncStatus.SENT)
            self.assertTrue(record.erp_id.startswith("NULL-"))

    # --------------------------------------------------------------------- MES
    def test_mes_tetap_jalan_walau_erp_tidak_terhubung(self):
        client = APIClient()
        client.force_authenticate(
            user=User.objects.create_user(
                username="fs-operator",
                password="rahasia",  # noqa: S106 - kredensial test
            )
        )
        bundle = make_bundle(code="BND-FS-1", qty=3)

        # Push lebih dulu (ERP "mati": adapter null)…
        sync = SyncIdempotency()
        payload = {"ref": "WO-FS-3", "qty": 1}
        record = sync.get_or_create_sync_record(
            "work_order", "WO-FS-3", SyncStage.WIP, payload
        )
        push_wip_issue.apply(args=("work_order", "WO-FS-3", payload, record.pk)).get()

        # …lalu aksi bundle SUNGGUHAN lewat endpoint MES → tetap berhasil.
        metadata = client.get(f"/api/v1/metadata/bundles/?id={bundle.pk}").json()
        action_id = metadata["state_machine"]["allowed_actions"][0]["id"]
        version = metadata["resource"]["version"]

        response = client.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action_id}/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"fs-{bundle.pk}",
            HTTP_X_BASE_VERSION=version,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        bundle.refresh_from_db()
        self.assertEqual(bundle.state, response.json()["state"])
        events = BundleEvent.objects.filter(bundle=bundle)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().event_type, action_id)
