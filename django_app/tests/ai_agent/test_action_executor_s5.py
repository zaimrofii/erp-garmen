"""Test S.5 — action executor HITL (LOG-ONLY) + integrasi approve."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.auth.models import Role, User
from integrations.ai_agent.hitl import action_executor, hitl_services
from integrations.ai_agent.models import AIHitlQueue

MODULE = "integrations.ai_agent.hitl.action_executor"


def _make_hitl(
    status: str = "APPROVED",
    action: str = "rework BND-A-12",
    nested: bool = True,
) -> AIHitlQueue:
    log = hitl_services.make_decision_log(
        {"query_text": "apa yang harus saya lakukan?", "decision_gate_result": "LLM_NEEDED"}
    )
    log.intent = "SUGGEST_ACTION"
    log.save(update_fields=["intent"])

    payload = (
        {
            "type": "suggest_actions",
            "problem": "scrap",
            "actions": [{"action": action, "impact": "MEDIUM", "confidence": 0.8}],
            "count": 1,
        }
        if nested
        else {"action": action, "resource": "bundle"}
    )

    return AIHitlQueue.objects.create(
        decision_log=log,
        risk_level="MEDIUM",
        proposed_action=payload,
        required_approver_role="SUPERVISOR",
        channel="DESKTOP",
        status=status,
        expires_at=timezone.now() + timedelta(hours=4),
    )


class ActionExecutorTests(TestCase):
    def test_hitl_tidak_ada_not_found(self):
        self.assertEqual(action_executor.execute(999999)["error"], "not_found")

    def test_status_pending_not_approved(self):
        hitl = _make_hitl(status="PENDING")

        result = action_executor.execute(hitl.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_approved")

    def test_aksi_rework(self):
        hitl = _make_hitl(action="rework BND-A-12")

        result = action_executor.execute(hitl.pk)

        self.assertTrue(result["executed"])
        self.assertIn("Rework dicatat", result["message"])

    def test_aksi_pindah(self):
        hitl = _make_hitl(action="pindah BND-A-14 ke SEWING-1")

        result = action_executor.execute(hitl.pk)

        self.assertTrue(result["executed"])
        self.assertIn("Pindah bundle dicatat", result["message"])

    def test_aksi_audit(self):
        hitl = _make_hitl(action="audit proses Line A")

        result = action_executor.execute(hitl.pk)

        self.assertTrue(result["executed"])
        self.assertIn("Audit dicatat", result["message"])

    def test_aksi_hentikan(self):
        hitl = _make_hitl(action="hentikan sementara SEWING-2")

        result = action_executor.execute(hitl.pk)

        self.assertTrue(result["executed"])
        self.assertIn("Pause dicatat", result["message"])

    def test_aksi_tidak_dikenal_hanya_dicatat(self):
        hitl = _make_hitl(action="hubungi vendor kain")

        result = action_executor.execute(hitl.pk)

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertIn("hanya dicatat", result["message"])

    def test_payload_lama_top_level_action(self):
        hitl = _make_hitl(action="rework bundle lama", nested=False)

        self.assertTrue(action_executor.execute(hitl.pk)["executed"])

    def test_executor_dipanggil_dengan_row(self):
        hitl = _make_hitl()

        with patch(f"{MODULE}._execute_rework", return_value="ok") as func:
            result = action_executor.execute(hitl.pk)

        func.assert_called_once()
        self.assertEqual(func.call_args.args[0].pk, hitl.pk)
        self.assertEqual(result["message"], "ok")

    def test_tidak_mengubah_status_atau_payload(self):
        hitl = _make_hitl()
        before = hitl.proposed_action

        action_executor.execute(hitl.pk)
        hitl.refresh_from_db()

        self.assertEqual(hitl.status, "APPROVED")
        self.assertEqual(hitl.proposed_action, before)

class ApproveIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supervisor = User.objects.create_user(
            username="exec-sup",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def test_approve_menjalankan_executor_dan_mengembalikan_execution(self):
        hitl = _make_hitl(status="PENDING", action="rework BND-A-12")

        result = hitl_services.approve(hitl.pk, self.supervisor, note="ok")

        self.assertEqual(result["status"], "APPROVED")
        self.assertEqual(result["hitl_id"], hitl.pk)
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("Rework dicatat", result["execution"]["message"])

    def test_approve_memanggil_action_executor(self):
        hitl = _make_hitl(status="PENDING")

        with patch(f"{MODULE}.execute", return_value={"ok": True, "executed": True}) as execute:
            hitl_services.approve(hitl.pk, self.supervisor)

        execute.assert_called_once_with(hitl.pk)

    def test_reject_tidak_menjalankan_executor(self):
        hitl = _make_hitl(status="PENDING")

        with patch(f"{MODULE}.execute") as execute:
            result = hitl_services.reject(hitl.pk, self.supervisor, "tidak perlu")

        execute.assert_not_called()
        self.assertEqual(result["status"], "REJECTED")

    def test_approve_dua_kali_conflict_dan_tidak_eksekusi_lagi(self):
        hitl = _make_hitl(status="PENDING")
        hitl_services.approve(hitl.pk, self.supervisor)

        with self.assertRaises(hitl_services.HitlConflict):
            hitl_services.approve(hitl.pk, self.supervisor)

