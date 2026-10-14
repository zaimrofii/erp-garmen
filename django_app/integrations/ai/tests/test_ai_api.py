"""Test stub AI chat (Fase F) — `POST /api/v1/ai/chat` selalu 200.

Endpoint nyata belum ada; yang penting bagi frontend (`ai-chat.ts`) adalah
respons **valid** (bukan 404/501) supaya jalur UI-nya bisa diuji tanpa LLM.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from integrations.ai.api import REASON_NOT_IMPLEMENTED, SCHEMA_VERSION

URL = "/api/v1/ai/chat"


class AiChatStubTests(TestCase):
    """Stub kontrak: 200 + `{ok:false, reason:'not_implemented'}`."""

    def setUp(self):
        self.client = APIClient()

    def test_post_200_dengan_body_kontrak(self):
        response = self.client.post(URL, {"message": "berapa bundle hari ini?"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "reason": REASON_NOT_IMPLEMENTED,
                "schema_version": SCHEMA_VERSION,
                "detail": "AI Chat belum diimplementasikan (stub Fase F).",
            },
        )

    def test_post_tanpa_body_tetap_200(self):
        response = self.client.post(URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])

    def test_alias_trailing_slash_dan_root_sama(self):
        for path in (f"{URL}/", "/api/ai/chat"):
            with self.subTest(path=path):
                response = self.client.post(path, {"message": "hai"}, format="json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["reason"], REASON_NOT_IMPLEMENTED)

    def test_bukan_404_dan_bukan_501(self):
        status = self.client.post(URL, {"message": "hai"}, format="json").status_code

        self.assertNotIn(status, (404, 501))

    def test_get_tidak_diizinkan(self):
        self.assertEqual(self.client.get(URL).status_code, 405)
