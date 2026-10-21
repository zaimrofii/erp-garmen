"""Test R.2 — disambiguation resolver + integrasi chat (mock, tanpa LLM)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.clarification import pending_state, resolver, templates
from integrations.ai_agent.clarification.resolver import ResolutionType
from integrations.ai_agent.orchestrator import response_synthesizer

URL = "/api/v1/ai/chat"

CANDIDATES = [
    {
        "id": 1,
        "label": "Kaos Sate Slamet",
        "attrs": {"order": "SO-042"},
        "score": 0.9,
    },
    {
        "id": 2,
        "label": "Baju Slametan Anak",
        "attrs": {"order": "SO-051"},
        "score": 0.9,
    },
    {
        "id": 3,
        "label": "Pak Slamet",
        "attrs": {"customer": "4 order aktif"},
        "score": 0.9,
    },
]


class ResolverBasicTests(SimpleTestCase):
    def test_yg_kedua_rank(self):
        result = resolver.resolve("yg kedua", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 2)

    def test_angka_dua_rank(self):
        result = resolver.resolve("2", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 2)

    def test_nomor_dua_rank_bukan_cancel(self):
        """Regresi: 'no' di dalam 'nomor' tidak boleh memicu CANCEL."""
        result = resolver.resolve("nomor 2", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 2)

    def test_pertama_rank(self):
        result = resolver.resolve("pertama", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 1)

    def test_kaos_sate_fuzzy(self):
        result = resolver.resolve("kaos sate", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.FUZZY)
        self.assertEqual(result.candidate["id"], 1)

    def test_bukan_itu_cancel(self):
        self.assertEqual(
            resolver.resolve("bukan itu", CANDIDATES).type, ResolutionType.CANCEL
        )

    def test_lupakan_cancel(self):
        self.assertEqual(
            resolver.resolve("lupakan", CANDIDATES).type, ResolutionType.CANCEL
        )

    def test_semua_all(self):
        self.assertEqual(
            resolver.resolve("semua", CANDIDATES).type, ResolutionType.ALL
        )

    def test_semuanya_all(self):
        self.assertEqual(
            resolver.resolve("semuanya", CANDIDATES).type, ResolutionType.ALL
        )

    def test_balasan_kosong_unresolved(self):
        result = resolver.resolve("   ", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.UNRESOLVED)
        self.assertIn("kosong", result.reason)

    def test_turn_melewati_batas_escalate(self):
        result = resolver.resolve("yg kedua", CANDIDATES, turn_count=3, max_turns=3)

        self.assertEqual(result.type, ResolutionType.ESCALATE)

    def test_angka_12_tidak_match_ordinal_2(self):
        """Word boundary: '12' bukan ordinal 2."""
        result = resolver.resolve("12", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.UNRESOLVED)

    def test_rank_lebih_dari_jumlah_kandidat(self):
        result = resolver.resolve("2", [CANDIDATES[0]])

        self.assertEqual(result.type, ResolutionType.UNRESOLVED)

    def test_fuzzy_ke_label(self):
        result = resolver.resolve("kaos", [{"id": 9, "label": "Kaos Polos", "attrs": {}}])

        self.assertEqual(result.type, ResolutionType.FUZZY)
        self.assertEqual(result.candidate["id"], 9)

    def test_fuzzy_ke_attrs(self):
        result = resolver.resolve("SO-042", CANDIDATES)

        self.assertEqual(result.type, ResolutionType.FUZZY)
        self.assertEqual(result.candidate["id"], 1)

    def test_tanpa_kandidat_cancel(self):
        result = resolver.resolve("yg kedua", [])

        self.assertEqual(result.type, ResolutionType.CANCEL)
        self.assertEqual(result.candidate, None)


class ResolverPendingStateTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_rank_memilih_kandidat_dari_state(self):
        pending_state.save(
            7,
            "sesi-1",
            {
                "candidates": CANDIDATES,
                "original_query": "slamet",
                "question": "Yang mana?",
                "turn_count": 0,
            },
        )
        state = pending_state.load(7, "sesi-1")

        result = resolver.resolve("kedua", state["candidates"])

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 2)

        pending_state.clear(7, "sesi-1")
        self.assertIsNone(pending_state.load(7, "sesi-1"))

    def test_cancel_clear_state(self):
        pending_state.save(
            7, "sesi-1", {"candidates": CANDIDATES, "turn_count": 0}
        )

        result = resolver.resolve("bukan itu", CANDIDATES)
        if result.type is ResolutionType.CANCEL:
            pending_state.clear(7, "sesi-1")

        self.assertIsNone(pending_state.load(7, "sesi-1"))

    def test_turn_bertambah_lalu_escalate(self):
        pending_state.save(
            7, "sesi-1", {"candidates": CANDIDATES, "turn_count": 0}
        )

        for expected in (1, 2, 3):
            self.assertEqual(pending_state.increment_turn(7, "sesi-1"), expected)

        result = resolver.resolve("entah", CANDIDATES, turn_count=3)

        self.assertEqual(result.type, ResolutionType.ESCALATE)

@override_settings(AI_AGENT_ENABLED=True)
class ChatClarificationWiringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="clarify-user", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.session_id = f"user-{self.user.pk}"

    def _save_pending(self, turn_count: int = 0) -> None:
        pending_state.save(
            self.user.pk,
            self.session_id,
            {
                "candidates": CANDIDATES,
                "original_query": "slamet",
                "question": "Yang mana?",
                "turn_count": turn_count,
            },
        )

    def test_cancel_menghapus_state_dan_rule_hit(self):
        self._save_pending()

        response = self.api.post(URL, {"message": "bukan itu"}, format="json")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        self.assertIn("lupakan", body["answer"])
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

    def test_unresolved_mengulang_pertanyaan_dan_menambah_turn(self):
        self._save_pending()

        response = self.api.post(URL, {"message": "zzz"}, format="json")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Yang mana?", body["answer"])
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertEqual(state["turn_count"], 1)

    def test_rank_menghapus_state_dan_lanjut_rule_hit(self):
        self._save_pending()

        with patch(
            "integrations.ai_agent.api.views.rule_evaluator.evaluate",
            return_value={
                "result": "RULE_HIT",
                "answer": "Diproses.",
                "rule_id": "RX",
                "tokens": 0,
            },
        ):
            response = self.api.post(URL, {"message": "kedua"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Diproses.")
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))


class AllResponseTests(SimpleTestCase):
    def test_all_response_daftar_kandidat(self):
        text = templates.all_response(CANDIDATES)

        self.assertIn("Berikut 3 data yang cocok:", text)
        self.assertIn("(2) Baju Slametan Anak", text)


class SynthesizerEmptyTests(SimpleTestCase):
    def test_empty_kandidat_tanpa_llm(self):
        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as provider:
            result = response_synthesizer.synthesize(
                "order Slamet",
                {
                    "message": "order Slamet",
                    "_candidates": [],
                    "_entity_label": "order",
                },
            )

        provider.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertIn("Tidak ada order untuk 'order Slamet'", result["answer"])
        self.assertEqual(result["tokens"]["total_cost_usd"], 0)
        self.assertEqual(result["model"], "rule:empty")

    def test_tanpa_candidates_tetap_panggil_llm(self):
        fake = SimpleNamespace(
            text="Jawaban LLM.",
            prompt_tokens=10,
            completion_tokens=5,
            total_cost_usd=0.001,
            model="deepseek-chat",
            latency_ms=12,
        )
        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as factory:
            factory.return_value.complete.return_value = fake
            result = response_synthesizer.synthesize("halo", {"message": "halo"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "Jawaban LLM.")
        factory.return_value.complete.assert_called_once()


