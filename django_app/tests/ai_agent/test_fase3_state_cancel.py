"""Test Fase 3 — lifecycle klarifikasi, cancel+remainder, pronoun carry-over."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.api.handlers.clarification import handle_pending_clarification
from integrations.ai_agent.clarification import pending_state, resolver
from integrations.ai_agent.orchestrator.conversation_context import (
    is_followup,
    resolve_followup,
)

URL = "/api/v1/ai/chat"
CANDIDATES = [
    {"id": index, "label": f"Kandidat {index}", "attrs": {"kode": f"K-{index}"}}
    for index in range(1, 6)
]


class StateLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fase3-state", password="x", role=Role.objects.get(code="SUPERVISOR")
        )
        self.session = f"user-{self.user.pk}"
        self.request = SimpleNamespace(user=self.user)
        pending_state.save(
            self.user.pk,
            self.session,
            {
                "candidates": CANDIDATES,
                "original_query": "produk termahal?",
                "question": "Yang mana?",
                "turn_count": 0,
                "entity": "product",
            },
        )

    def send(self, message: str):
        return handle_pending_clarification(
            self.request,
            message,
            session_id=self.session,
            started=time.monotonic(),
        )

    def test_tiga_rank_berurutan_tidak_clear(self):
        for message in ("kedua", "ketiga", "keempat"):
            self.assertIsNone(self.send(message))
            self.assertIsNotNone(pending_state.load(self.user.pk, self.session))

        state = pending_state.load(self.user.pk, self.session)
        self.assertEqual(state["successful_rank_count"], 3)
        self.assertEqual(state["turn_count"], 3)
        self.assertEqual(state["failed_clarification_count"], 0)
        self.assertEqual(state["selected_id"], 4)

    def test_lima_rank_berurutan_tidak_clear(self):
        for message in ("kedua", "ketiga", "keempat", "kelima", "pertama"):
            self.assertIsNone(self.send(message))
            self.assertIsNotNone(pending_state.load(self.user.pk, self.session))

        state = pending_state.load(self.user.pk, self.session)
        self.assertEqual(state["successful_rank_count"], 5)
        self.assertGreaterEqual(state["turn_count"], 5)

    def test_rank_setelah_cancel_state_baru_berhasil(self):
        self.assertIsNotNone(self.send("bukan itu"))
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

        pending_state.save(
            self.user.pk,
            self.session,
            {
                "candidates": CANDIDATES,
                "original_query": "produk termahal?",
                "turn_count": 0,
                "entity": "product",
            },
        )
        self.assertIsNone(self.send("kedua"))
        state = pending_state.load(self.user.pk, self.session)
        self.assertIsNotNone(state)
        self.assertEqual(state["successful_rank_count"], 1)

    def test_tiga_kegagalan_eskalasi_dan_clear(self):
        for _ in range(2):
            response = self.send("zzz")
            self.assertIsNotNone(response)
            self.assertIsNotNone(pending_state.load(self.user.pk, self.session))

        response = self.send("zzz")
        self.assertIsNotNone(response)
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

class CancelRemainderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fase3-cancel",
            password="x",
            role=Role.objects.get(code="SUPERVISOR"),
        )
        self.session = f"user-{self.user.pk}"
        self.request = SimpleNamespace(user=self.user)
        pending_state.save(
            self.user.pk,
            self.session,
            {
                "candidates": CANDIDATES,
                "original_query": "produk termahal?",
                "turn_count": 0,
            },
        )

    def send(self, message: str):
        return handle_pending_clarification(
            self.request,
            message,
            session_id=self.session,
            started=time.monotonic(),
        )

    def test_lupakan_dengan_remainder_total_order(self):
        self.assertIsNone(self.send("lupakan, total order?"))
        self.assertEqual(self.request._ai_remainder, "total order?")
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

    def test_batal_dengan_remainder_tren_scrap(self):
        self.assertIsNone(self.send("batal, tren scrap?"))
        self.assertEqual(self.request._ai_remainder, "tren scrap?")
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

    def test_lupakan_tanpa_remainder_tetap_balas_lupakan(self):
        response = self.send("lupakan")
        self.assertIsNotNone(response)
        self.assertIn("lupakan", response.data["answer"])
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

    def test_resolver_remainder_tidak_menempel_di_bukan_itu(self):
        result = resolver.resolve("bukan itu", CANDIDATES)
        self.assertEqual(result.type, resolver.ResolutionType.CANCEL)
        self.assertIsNone(result.remainder)

    def test_lupakan_berapa_total_order_tetap_remainder(self):
        self.assertIsNone(self.send("lupakan, berapa total order?"))
        self.assertEqual(self.request._ai_remainder, "berapa total order?")
        self.assertIsNone(pending_state.load(self.user.pk, self.session))



@override_settings(AI_AGENT_ENABLED=True)
class CancelRemainderApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fase3-remainder-api",
            password="x",
            role=Role.objects.get(code="SUPERVISOR"),
        )
        from django.core.cache import cache

        cache.clear()
        self.session = f"user-{self.user.pk}"
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        pending_state.save(
            self.user.pk,
            self.session,
            {
                "candidates": CANDIDATES,
                "original_query": "produk termahal?",
                "turn_count": 0,
            },
        )
        self.captured = {}

        def builder(_intent, _tools, message, context=None, **_kwargs):
            self.captured["message"] = message
            return {"message": message, "context": {}, "tools": []}

        def synth(message, context_data, **kwargs):
            self.captured["synth_message"] = message
            answer = "50 order." if "total order" in message else "Tren scrap."
            return {
                "ok": True,
                "answer": answer,
                "tokens": {"prompt": 0, "completion": 0, "total_cost_usd": 0},
                "model": "mock",
                "latency_ms": 1,
            }

        self.patches = [
            patch(
                "integrations.ai_agent.api.views.rule_evaluator.evaluate",
                return_value={"result": "LLM_NEEDED", "answer": None},
            ),
            patch(
                "integrations.ai_agent.api.views.intent_classifier.classify",
                return_value={"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0},
            ),
            patch(
                "integrations.ai_agent.api.views.tool_selector.select_tools",
                return_value=["mcp-postgres-query"],
            ),
            patch(
                "integrations.ai_agent.api.views.context_builder.build_context",
                side_effect=builder,
            ),
            patch(
                "integrations.analytics.services.analytics_config_services.analytics_enabled",
                return_value=True,
            ),
            patch(
                "integrations.ai_agent.api.views.response_synthesizer.synthesize",
                side_effect=synth,
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_lupakan_total_order_dijawab_pipeline_remainder(self):
        response = self.api.post(
            URL, {"message": "lupakan, total order?"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("50 order", response.json()["answer"])
        self.assertEqual(self.captured["message"], "total order?")
        self.assertIsNone(pending_state.load(self.user.pk, self.session))

    def test_batal_tren_scrap_dijawab_pipeline_remainder(self):
        response = self.api.post(URL, {"message": "batal, tren scrap?"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.captured["message"], "tren scrap?")
        self.assertIsNone(pending_state.load(self.user.pk, self.session))



class PronounCarryOverTests(TestCase):
    def test_bundle_code_ke_order_apa(self):
        history = [
            {"role": "user", "content": "bundle BND-A-01?"},
            {"role": "assistant", "content": "Bundle BND-A-01 ada di packing."},
        ]
        result = resolve_followup("order apa?", history)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["entity_type"], "bundle")
        self.assertEqual(result["entity_code"], "BND-A-01")
        self.assertEqual(result["target_entity"], "bundle")
        self.assertIn("BND-A-01", result["resolved_message"])

    def test_order_code_ke_customer_siapa(self):
        history = [
            {"role": "user", "content": "order SO-2026-0001?"},
            {"role": "assistant", "content": "Order tersebut milik PT Retail."},
        ]
        result = resolve_followup("customer siapa?", history)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["entity_type"], "order")
        self.assertEqual(result["entity_code"], "SO-2026-0001")
        self.assertEqual(result["target_entity"], "order")

    def test_produk_ke_harganya(self):
        history = [
            {"role": "user", "content": "produk Kaos?"},
            {"role": "assistant", "content": "Kaos tersedia."},
        ]
        result = resolve_followup("harganya?", history)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["entity_type"], "product")
        self.assertEqual(result["entity_name"], "Kaos")
        self.assertEqual(result["target_entity"], "product")

    def test_pronoun_bundle_itu(self):
        history = [
            {"role": "user", "content": "bundle BND-A-01?"},
            {"role": "assistant", "content": "Bundle BND-A-01."},
        ]
        result = resolve_followup("bundle itu order apa?", history)

        self.assertTrue(is_followup("bundle itu order apa?"))
        self.assertTrue(result["is_followup"])
        self.assertEqual(result["entity_code"], "BND-A-01")



class CacheBypassTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fase35-cache",
            password="x",
            role=Role.objects.get(code="SUPERVISOR"),
        )
        self.session = f"user-{self.user.pk}"
        self.request = SimpleNamespace(user=self.user)

    def test_pending_state_bypass(self):
        from integrations.ai_agent.api.handlers.llm_pipeline import should_bypass_cache

        pending_state.save(self.user.pk, self.session, {"candidates": CANDIDATES})
        self.assertTrue(should_bypass_cache(self.request, "kedua?", [], self.session))

    def test_followup_history_bypass(self):
        from integrations.ai_agent.api.handlers.llm_pipeline import should_bypass_cache

        history = [
            {"role": "user", "content": "bundle BND-A-01?"},
            {"role": "assistant", "content": "Bundle."},
        ]
        self.assertTrue(
            should_bypass_cache(self.request, "order apa?", history, self.session)
        )

    def test_normal_message_tidak_bypass(self):
        from integrations.ai_agent.api.handlers.llm_pipeline import should_bypass_cache

        self.assertFalse(
            should_bypass_cache(self.request, "total order?", [], self.session)
        )

    def test_remainder_attr_bypass(self):
        from integrations.ai_agent.api.handlers.llm_pipeline import should_bypass_cache

        setattr(self.request, "_ai_remainder", "total order?")
        self.assertTrue(
            should_bypass_cache(self.request, "total order?", [], self.session)
        )

    def test_state_hash_membedakan_cache_key(self):
        from integrations.ai_agent.api.handlers.llm_pipeline import build_cache_scope

        with patch(
            "integrations.ai_agent.api.handlers.llm_pipeline._data_version",
            return_value="v1",
        ):
            one = build_cache_scope("SUPERVISOR", "DESKTOP", "kedua?", {}, [], "a")
            two = build_cache_scope("SUPERVISOR", "DESKTOP", "kedua?", {}, [], "b")
        self.assertNotEqual(one, two)


class EmptyFollowupTests(TestCase):
    def test_bundle_tidak_ada_tidak_carry_over(self):
        from integrations.ai_agent.orchestrator.context_builder import build_context
        from integrations.ai_agent.orchestrator.response_synthesizer import synthesize

        history = [
            {"role": "user", "content": "bundle BND-A-01?"},
            {"role": "assistant", "content": "Bundle BND-A-01."},
        ]
        data = build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], "order apa?", {}, history=history
        )
        self.assertEqual(
            data["_followup_empty"], {"entity": "bundle", "code": "BND-A-01"}
        )

        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as provider:
            result = synthesize("order apa?", data)

        provider.assert_not_called()
        self.assertIn("Bundle BND-A-01 tidak ada", result["answer"])
        self.assertIn("order", result["answer"])

    def test_empty_followup_clear_state(self):
        from integrations.ai_agent.orchestrator.context_builder import build_context
        from integrations.ai_agent.orchestrator.response_synthesizer import synthesize

        user = User.objects.create_user(
            username="fase35-empty",
            password="x",
            role=Role.objects.get(code="SUPERVISOR"),
        )
        session = f"user-{user.pk}"
        pending_state.save(user.pk, session, {"candidates": CANDIDATES})
        history = [
            {"role": "user", "content": "bundle BND-A-01?"},
            {"role": "assistant", "content": "Bundle BND-A-01."},
        ]
        data = build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], "order apa?", {}, history=history
        )

        result = synthesize("order apa?", data, user=user, session_id=session)

        self.assertIn("tidak ada", result["answer"])
        self.assertIsNone(pending_state.load(user.pk, session))

