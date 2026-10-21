"""Test R.3 — klarifikasi AMBIGUOUS end-to-end (mock, tanpa LLM nyata)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.clarification import pending_state
from integrations.ai_agent.orchestrator import context_builder
from integrations.ai_agent.orchestrator.text_normalizer import normalize

URL = "/api/v1/ai/chat"
BUILD = "integrations.ai_agent.api.views.context_builder.build_context"
INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"
LOAD = "integrations.ai_agent.api.views.pending_state.load"
PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"

CANDIDATES = [
    {
        "id": 1,
        "label": "Kaos Sate Slamet",
        "attrs": {"kode": "K-1"},
        "score": 0.7,
        "entity": "product",
    },
    {
        "id": 2,
        "label": "Kaos Sate Anak",
        "attrs": {"kode": "K-2"},
        "score": 0.7,
        "entity": "product",
    },
    {
        "id": 3,
        "label": "Kaos Sate Dewasa",
        "attrs": {"kode": "K-3"},
        "score": 0.7,
        "entity": "product",
    },
]


def _context(candidates=None, entity_label=None, resolved=None) -> dict:
    data = {
        "intent": "DATA_LOOKUP",
        "message": "uji",
        "context": {},
        "tools": [],
    }
    if candidates is not None:
        data["_candidates"] = candidates
    if entity_label is not None:
        data["_entity_label"] = entity_label
    if resolved is not None:
        data["_resolved_candidate"] = resolved
    return data


def _fake_response(text="Jawaban LLM.") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        prompt_tokens=10,
        completion_tokens=5,
        total_cost_usd=0.001,
        model="deepseek-chat",
        latency_ms=12,
    )


@override_settings(AI_AGENT_ENABLED=True)
class ClarificationE2ETests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="e2e-clarify", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.session_id = f"user-{self.user.pk}"

        self.intent_patch = patch(
            INTENT,
            return_value={"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0},
        )
        self.tools_patch = patch(TOOLS, return_value=[])
        self.intent_patch.start()
        self.tools_patch.start()

    def tearDown(self):
        self.intent_patch.stop()
        self.tools_patch.stop()
        super().tearDown()

    def _save_pending(self, turn_count: int = 0) -> None:
        pending_state.save(
            self.user.pk,
            self.session_id,
            {
                "candidates": CANDIDATES,
                "original_query": "kaos sate mana?",
                "question": "Yang mana?",
                "turn_count": turn_count,
                "entity": "product",
            },
        )

    def test_ambiguous_menyimpan_state_dan_tanya(self):
        with patch(BUILD, return_value=_context(CANDIDATES, "produk")), patch(
            PROVIDER
        ) as provider:
            response = self.api.post(
                URL, {"message": "kaos sate mana?"}, format="json"
            )

        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ada 3 yang cocok:", body["answer"])
        self.assertIn("Yang mana?", body["answer"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        provider.assert_not_called()
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertEqual(len(state["candidates"]), 3)
        self.assertEqual(state["turn_count"], 0)

    def test_rank_memilih_kandidat_dan_lanjut_llm(self):
        self._save_pending()
        captured: dict = {}

        def builder(_intent, _tools, _message, context=None, **_kwargs):
            captured.update(context or {})
            return _context()

        with patch(BUILD, side_effect=builder), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = _fake_response()
            response = self.api.post(URL, {"message": "yg kedua"}, format="json")

        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["answer"], "Jawaban LLM.")
        self.assertEqual(captured["_resolved_candidate"]["id"], 2)
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["turn_count"], 1)

    def test_fuzzy_memilih_kandidat(self):
        self._save_pending()
        captured: dict = {}

        def builder(_intent, _tools, _message, context=None, **_kwargs):
            captured.update(context or {})
            return _context()

        with patch(BUILD, side_effect=builder), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = _fake_response()
            response = self.api.post(
                URL, {"message": "kaos sate dewasa"}, format="json"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["_resolved_candidate"]["id"], 3)
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["turn_count"], 1)

    def test_cancel_membersihkan_state(self):
        self._save_pending()

        response = self.api.post(URL, {"message": "bukan itu"}, format="json")
        body = response.json()

        self.assertIn("lupakan", body["answer"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

    def test_all_menjawab_agregat(self):
        self._save_pending()

        response = self.api.post(URL, {"message": "semua"}, format="json")
        body = response.json()

        self.assertIn("Berikut 3 data yang cocok:", body["answer"])
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

    def test_tiga_turn_tanpa_resolve_eskalasi(self):
        self._save_pending(turn_count=2)

        response = self.api.post(URL, {"message": "zzz"}, format="json")
        body = response.json()

        self.assertIn("kriteria tambahan", body["answer"])
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

    def test_empty_tanpa_llm(self):
        message = "produk KPP-DEWASA-V2?"

        with patch(
            BUILD, return_value=_context([], "produk")
        ), patch(PROVIDER) as provider:
            response = self.api.post(URL, {"message": message}, format="json")

        body = response.json()

        self.assertIn(f"Tidak ada produk untuk '{message}'", body["answer"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        provider.assert_not_called()

    def test_exact_lanjut_llm(self):
        exact = [dict(CANDIDATES[0], score=0.9)]

        with patch(BUILD, return_value=_context(exact, "produk")), patch(
            PROVIDER
        ) as provider:
            provider.return_value.complete.return_value = _fake_response()
            response = self.api.post(
                URL, {"message": "produk kaos sate slamet"}, format="json"
            )

        body = response.json()

        self.assertEqual(body["answer"], "Jawaban LLM.")
        provider.return_value.complete.assert_called_once()
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

    def test_state_expired_lanjut_normal(self):
        with patch(LOAD, return_value=None), patch(
            BUILD, return_value=_context()
        ), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = _fake_response()
            response = self.api.post(URL, {"message": "halo"}, format="json")

        self.assertEqual(response.json()["answer"], "Jawaban LLM.")
        provider.return_value.complete.assert_called_once()

    def test_topik_baru_saat_ada_state_membersihkan_state(self):
        self._save_pending()

        with patch(BUILD, return_value=_context()), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = _fake_response()
            response = self.api.post(
                URL, {"message": "berapa produk aktif?"}, format="json"
            )

        self.assertEqual(response.json()["answer"], "Jawaban LLM.")
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))


class CandidateHeuristicTests(SimpleTestCase):
    def test_query_daftar_tidak_memicu_kandidat(self):
        candidates, entity = context_builder._collect_candidates(
            normalize("produk apa saja?"), {}
        )

        self.assertEqual(candidates, [])
        self.assertIsNone(entity)

    def test_query_spesifik_memilih_baris_paling_cocok(self):
        data = {
            "product_list": [
                {"id": 1, "name": "Kaos Sate", "code": "K-1"},
                {"id": 2, "name": "Kaos Polos", "code": "K-2"},
            ]
        }

        candidates, entity = context_builder._collect_candidates(
            normalize("produk kaos sate"), data
        )

        self.assertEqual(entity, "product")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["label"], "Kaos Sate")
        self.assertEqual(candidates[0]["score"], 0.9)

    def test_beberapa_cocok_sama_jadi_kandidat_ambigu(self):
        data = {
            "product_list": [
                {"id": 1, "name": "Kaos Slamet", "code": "K-1"},
                {"id": 2, "name": "Kaos Slamet Anak", "code": "K-2"},
            ]
        }

        candidates, entity = context_builder._collect_candidates(
            normalize("produk kaos slamet"), data
        )

        self.assertEqual(entity, "product")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["score"], 0.7)

    def test_kode_tidak_ditemukan_menghasilkan_kandidat_kosong(self):
        data = {"product_list": [{"id": 1, "name": "Kaos Polos", "code": "K-1"}]}

        candidates, entity = context_builder._collect_candidates(
            normalize("produk KPP-DEWASA-V2"), data
        )

        self.assertEqual(entity, "product")
        self.assertEqual(candidates, [])

    def test_resolved_candidate_filter_id_dan_clear_kandidat(self):
        fake_repo = SimpleNamespace(
            get_list=lambda filters=None, limit=20: [
                {"id": 7, "name": "Kaos Sate", "code": "K-7"}
            ]
        )

        with patch.object(context_builder, "get_repo", return_value=fake_repo):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                [],
                "halo",
                {
                    "_resolved_candidate": {
                        "id": 7,
                        "entity": "product",
                        "label": "Kaos Sate",
                    }
                },
            )

        self.assertEqual(data["_candidates"], [])
        self.assertEqual(data["_entity_label"], "produk")
        self.assertEqual(data["product_list"][0]["id"], 7)
        self.assertEqual(data["_resolved_candidate"]["id"], 7)


