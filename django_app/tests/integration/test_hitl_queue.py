"""Test endpoint HITL Queue (F5.4.2 / B29).

Cakupan: ``GET /api/v1/ai/hitl/queue/`` + ``POST /api/v1/ai/hitl/<id>/approve|reject/``.
Model: ``apps_industry.garment.models.HITLRequest`` (migration ``garment.0011``).

Aturan yang diuji:

  * ListPage + default filter ``state=PENDING``;
  * keputusan hanya sah dari ``PENDING`` → selain itu **409**;
  * ``reject`` wajib ``note`` → tanpa note **400** (state tidak berubah);
  * pemutus = admin/owner/**supervisor** (role lain **403**, anonim **403**);
  * notifikasi WA best-effort (tanpa nomor tujuan terkonfigurasi = dilewati, tidak
    pernah menggagalkan keputusan);
  * ``expires_at`` dikembalikan apa adanya — penandaan ``EXPIRED`` otomatis belum
    ada (butuh task beat), jadi **bukan** bagian test ini.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_hitl_queue.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps_industry.garment.models import HITLRequest
from core.auth.models import Role, User

QUEUE_URL = "/api/v1/ai/hitl/queue/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "request_type",
    "resource_type",
    "resource_id",
    "payload",
    "reason",
    "priority",
    "state",
    "requested_by",
    "requested_at",
    "expires_at",
    "decided_by",
    "decided_at",
    "decision_note",
}


def approve_url(pk: int) -> str:
    """URL approve satu permintaan."""
    return f"/api/v1/ai/hitl/{pk}/approve/"


def reject_url(pk: int) -> str:
    """URL reject satu permintaan."""
    return f"/api/v1/ai/hitl/{pk}/reject/"


class HitlQueueTests(TestCase):
    """Queue + keputusan HITL."""

    @classmethod
    def setUpTestData(cls):
        """Role seed + 4 permintaan (2 PENDING, 1 APPROVED, 1 REJECTED)."""
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.supervisor_role = Role.objects.get(code=Role.Code.SUPERVISOR)

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
            role=cls.operator_role,
        )
        cls.supervisor = User.objects.create_user(
            username="spv1",
            email="spv1@klien.com",
            password="rahasia123",
            role=cls.supervisor_role,
        )

        cls.pending_high = HITLRequest.objects.create(
            request_type="OVERLAP_RELEASE",
            resource_type="bundle",
            resource_id="42",
            payload={"overlap_pct": 80},
            reason="Overlap 80% > 50% default",
            state=HITLRequest.State.PENDING,
            priority=HITLRequest.Priority.HIGH,
            requested_by=cls.operator,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        cls.pending_medium = HITLRequest.objects.create(
            request_type="BUNDLE_SPLIT",
            resource_type="work_order",
            resource_id="WO-1",
            reason="Split otomatis usulan agen",
            priority=HITLRequest.Priority.MEDIUM,
            requested_by=cls.operator,
        )
        cls.approved = HITLRequest.objects.create(
            request_type="OVERLAP_RELEASE",
            resource_type="bundle",
            resource_id="7",
            reason="Overlap 60%",
            state=HITLRequest.State.APPROVED,
            priority=HITLRequest.Priority.LOW,
            requested_by=cls.operator,
            decided_by=cls.admin,
            decided_at=timezone.now(),
            decision_note="disetujui",
        )
        cls.rejected = HITLRequest.objects.create(
            request_type="BUNDLE_SPLIT",
            resource_type="order",
            resource_id="ORD-1",
            reason="Split tidak perlu",
            state=HITLRequest.State.REJECTED,
            priority=HITLRequest.Priority.MEDIUM,
            requested_by=cls.operator,
            decided_by=cls.admin,
            decided_at=timezone.now(),
            decision_note="tidak sesuai spec",
        )

    def setUp(self):
        """Klien admin, operator (403), supervisor (boleh memutuskan)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)
        self.supervisor_api = APIClient()
        self.supervisor_api.force_authenticate(self.supervisor)

    # -------------------------------------------------------------------- GET
    def test_get_shape_listpage(self):
        """Bentuk ListPage + field baris sesuai kontrak B29."""
        response = self.api.get(QUEUE_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 2)  # default: PENDING saja
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

        row = next(item for item in body["rows"] if item["id"] == self.pending_high.pk)
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["request_type"], "OVERLAP_RELEASE")
        self.assertEqual(row["resource_type"], "bundle")
        self.assertEqual(row["resource_id"], "42")
        self.assertEqual(row["priority"], "HIGH")
        self.assertEqual(row["state"], "PENDING")
        self.assertEqual(row["requested_by"], "operator1")
        self.assertIsNone(row["decided_by"])
        self.assertIn("T", row["requested_at"])
        self.assertIsNotNone(row["expires_at"])

    def test_get_anonim_403(self):
        """Tanpa login → 403."""
        self.assertEqual(APIClient().get(QUEUE_URL).status_code, 403)

    def test_get_kosong(self):
        """Belum ada permintaan → rows kosong, bukan error."""
        HITLRequest.objects.all().delete()

        body = self.api.get(QUEUE_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_get_default_filter_pending(self):
        """Tanpa `?state` → hanya PENDING (default)."""
        body = self.api.get(QUEUE_URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertTrue(all(row["state"] == "PENDING" for row in body["rows"]))

    def test_get_filter_state_approved(self):
        """`?state=APPROVED` → hanya baris APPROVED (+ info pemutus)."""
        body = self.api.get(f"{QUEUE_URL}?state=APPROVED").json()

        self.assertEqual(body["total_count"], 1)
        row = body["rows"][0]
        self.assertEqual(row["id"], self.approved.pk)
        self.assertEqual(row["state"], "APPROVED")
        self.assertEqual(row["decided_by"], "admin")
        self.assertEqual(row["decision_note"], "disetujui")

    def test_get_filter_priority_high(self):
        """`?priority=HIGH` → hanya baris prioritas HIGH."""
        body = self.api.get(f"{QUEUE_URL}?priority=HIGH").json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["id"], self.pending_high.pk)

    def test_get_filter_resource_type(self):
        """`?resource_type=` case-insensitive."""
        body = self.api.get(f"{QUEUE_URL}?resource_type=WORK_ORDER").json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["id"], self.pending_medium.pk)

    def test_get_state_tidak_dikenal_400(self):
        """`?state=` di luar enum → 400 dengan detail jelas."""
        response = self.api.get(f"{QUEUE_URL}?state=SELESAI")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak dikenal", response.json()["detail"])

    # -------------------------------------------------------- POST keputusan
    def test_post_approve_200(self):
        """Approve dari PENDING → APPROVED + pemutus & waktu tercatat."""
        response = self.api.post(
            approve_url(self.pending_high.pk), {"note": "ok, lanjutkan"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], self.pending_high.pk)
        self.assertEqual(body["state"], "APPROVED")
        self.assertEqual(body["decided_by"], "admin")
        self.assertEqual(body["decision_note"], "ok, lanjutkan")
        self.assertIsNotNone(body["decided_at"])

        self.pending_high.refresh_from_db()
        self.assertEqual(self.pending_high.state, "APPROVED")
        self.assertEqual(self.pending_high.decided_by, self.admin)
        self.assertIsNotNone(self.pending_high.decided_at)

    def test_post_approve_id_tidak_ada_404(self):
        """Approve id tak dikenal → 404."""
        self.assertEqual(
            self.api.post(approve_url(999999), {}, format="json").status_code, 404
        )

    def test_post_approve_state_bukan_pending_409(self):
        """Approve baris yang sudah APPROVED → 409 Conflict (state tidak berubah)."""
        response = self.api.post(approve_url(self.approved.pk), {"note": "lagi"}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["state"], "APPROVED")

        self.approved.refresh_from_db()
        self.assertEqual(self.approved.decision_note, "disetujui")

    def test_post_reject_200(self):
        """Reject dari PENDING dengan note → REJECTED + catatan tersimpan."""
        response = self.api.post(
            reject_url(self.pending_medium.pk),
            {"note": "tidak sesuai spec produksi"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "REJECTED")
        self.assertEqual(body["decision_note"], "tidak sesuai spec produksi")

        self.pending_medium.refresh_from_db()
        self.assertEqual(self.pending_medium.state, "REJECTED")
        self.assertEqual(self.pending_medium.decided_by, self.admin)

    def test_post_reject_tanpa_note_400(self):
        """Reject tanpa `note` → 400 dan state TETAP PENDING."""
        response = self.api.post(reject_url(self.pending_high.pk), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("note", response.json()["detail"])

        self.pending_high.refresh_from_db()
        self.assertEqual(self.pending_high.state, "PENDING")
        self.assertIsNone(self.pending_high.decided_at)

    def test_post_reject_id_tidak_ada_404(self):
        """Reject id tak dikenal → 404."""
        self.assertEqual(
            self.api.post(reject_url(999999), {"note": "x"}, format="json").status_code,
            404,
        )

    def test_post_anonim_403(self):
        """Tanpa login → 403 (tidak ada keputusan tersimpan)."""
        response = APIClient().post(approve_url(self.pending_high.pk), {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.pending_high.refresh_from_db()
        self.assertEqual(self.pending_high.state, "PENDING")

    def test_post_non_approver_403(self):
        """Role OPERATOR bukan pemutus → 403 (admin/owner/supervisor saja)."""
        response = self.operator_api.post(approve_url(self.pending_high.pk), {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.pending_high.refresh_from_db()
        self.assertEqual(self.pending_high.state, "PENDING")

    def test_post_supervisor_boleh_memutuskan(self):
        """Supervisor termasuk pemutus (keputusan F5.4.2)."""
        response = self.supervisor_api.post(
            reject_url(self.pending_high.pk), {"note": "ditolak supervisor"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "REJECTED")
        self.assertEqual(response.json()["decided_by"], "spv1")

    def test_expires_at_dikembalikan_apa_adanya(self):
        """`expires_at` = nilai DB (belum ada auto-EXPIRED; butuh beat)."""
        body = self.api.get(QUEUE_URL).json()
        row = next(item for item in body["rows"] if item["id"] == self.pending_high.pk)

        self.assertEqual(row["state"], "PENDING")
        self.assertEqual(
            parse_datetime(row["expires_at"]), self.pending_high.expires_at
        )
