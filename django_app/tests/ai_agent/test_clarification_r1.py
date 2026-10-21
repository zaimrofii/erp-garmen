"""Test R.1 — epistemic classifier + pending state + templates (tanpa LLM)."""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from integrations.ai_agent.clarification import (
    EpistemicStatus,
    classify,
    pending_state,
    templates,
)

PATCH_GET = "integrations.ai_agent.clarification.pending_state.cache.get"
PATCH_SET = "integrations.ai_agent.clarification.pending_state.cache.set"


def _candidate(label="Kaos Sate Slamet", score=0.9, answer_hash=None, **attrs):
    return {
        "id": label,
        "label": label,
        "attrs": attrs,
        "score": score,
        "answer_hash": answer_hash,
    }


class EpistemicClassifierTests(SimpleTestCase):
    def test_tanpa_kandidat_empty(self):
        result = classify([], "order Slamet")

        self.assertEqual(result.status, EpistemicStatus.EMPTY)
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.question)
        self.assertIn("Tidak ada data", result.reason)

    def test_satu_kandidat_skor_tinggi_exact(self):
        result = classify([_candidate(score=0.9)], "kaos sate")

        self.assertEqual(result.status, EpistemicStatus.EXACT)
        self.assertEqual(len(result.candidates), 1)
        self.assertIn("skor tinggi", result.reason)

    def test_satu_kandidat_skor_rendah_weak(self):
        result = classify([_candidate(score=0.6)], "kaos sate")

        self.assertEqual(result.status, EpistemicStatus.WEAK)
        self.assertIn("skor rendah", result.reason)

    def test_tiga_kandidat_berbeda_ambiguous(self):
        candidates = [
            _candidate("Kaos A", answer_hash="a"),
            _candidate("Kaos B", answer_hash="b"),
            _candidate("Kaos C", answer_hash="c"),
        ]

        result = classify(candidates, "kaos")

        self.assertEqual(result.status, EpistemicStatus.AMBIGUOUS)
        self.assertEqual(len(result.candidates), 3)
        self.assertIn("3 kandidat", result.reason)

    def test_answer_hash_sama_tidak_perlu_tanya(self):
        candidates = [
            _candidate("Kaos A", answer_hash="sama"),
            _candidate("Kaos B", answer_hash="sama"),
            _candidate("Kaos C", answer_hash="sama"),
        ]

        result = classify(candidates, "kaos")

        self.assertEqual(result.status, EpistemicStatus.EXACT)
        self.assertEqual(len(result.candidates), 3)
        self.assertIn("jawaban sama", result.reason)

    def test_answer_hash_sebagian_tidak_dianggap_sama(self):
        candidates = [
            _candidate("Kaos A", answer_hash="sama"),
            _candidate("Kaos B", answer_hash=None),
        ]

        result = classify(candidates, "kaos")

        self.assertEqual(result.status, EpistemicStatus.AMBIGUOUS)

    def test_query_terlalu_pendek_out_of_scope(self):
        for query in ("", "   ", "x"):
            with self.subTest(query=query):
                result = classify([_candidate()], query)
                self.assertEqual(result.status, EpistemicStatus.OUT_OF_SCOPE)
                self.assertEqual(result.candidates, [])

    def test_kandidat_lebih_dari_batas_dipotong(self):
        candidates = [
            _candidate(f"Kaos {index}", answer_hash=f"h{index}")
            for index in range(7)
        ]

        result = classify(candidates, "kaos")

        self.assertEqual(result.status, EpistemicStatus.AMBIGUOUS)
        self.assertEqual(len(result.candidates), 5)
        self.assertIn("7 kandidat", result.reason)


class PendingStateTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_save_load_state_sama(self):
        state = {
            "candidates": [{"id": 1, "label": "Kaos A"}],
            "original_query": "slamet",
            "question": "Yang mana?",
            "turn_count": 0,
        }

        pending_state.save(7, "sesi-1", state)
        loaded = pending_state.load(7, "sesi-1")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["original_query"], "slamet")
        self.assertEqual(loaded["question"], "Yang mana?")
        self.assertEqual(loaded["turn_count"], 0)
        self.assertEqual(loaded["candidates"], [{"id": 1, "label": "Kaos A"}])
        self.assertIn("updated_at", loaded)

    def test_save_tidak_mengubah_dict_pemanggil(self):
        state = {"original_query": "slamet", "turn_count": 0}

        pending_state.save(7, "sesi-1", state)

        self.assertNotIn("updated_at", state)

    def test_clear_menghapus_state(self):
        pending_state.save(7, "sesi-1", {"original_query": "slamet"})

        pending_state.clear(7, "sesi-1")

        self.assertIsNone(pending_state.load(7, "sesi-1"))

    def test_increment_turn_naik(self):
        pending_state.save(7, "sesi-1", {"original_query": "x", "turn_count": 0})

        self.assertEqual(pending_state.increment_turn(7, "sesi-1"), 1)
        self.assertEqual(pending_state.increment_turn(7, "sesi-1"), 2)
        self.assertEqual(pending_state.load(7, "sesi-1")["turn_count"], 2)

    def test_increment_turn_tanpa_state_nol(self):
        self.assertEqual(pending_state.increment_turn(99, "tidak-ada"), 0)

    def test_expired_setelah_tiga_turn(self):
        self.assertFalse(pending_state.is_expired_by_turns({"turn_count": 2}))
        self.assertTrue(pending_state.is_expired_by_turns({"turn_count": 3}))

    def test_ttl_sepuluh_menit(self):
        with patch(PATCH_SET) as set_mock:
            pending_state.save(7, "sesi-1", {"original_query": "x"})

        args, _kwargs = set_mock.call_args
        self.assertEqual(args[0], "clarification:7:sesi-1")
        self.assertIn("updated_at", args[1])
        self.assertEqual(args[2], pending_state.TTL_SECONDS)
        self.assertEqual(pending_state.TTL_SECONDS, 600)

    def test_load_setelah_expire_none(self):
        with patch(PATCH_GET, return_value=None):
            self.assertIsNone(pending_state.load(7, "sesi-1"))

    def test_state_rusak_diabaikan(self):
        with patch(PATCH_GET, return_value="bukan-json"):
            self.assertIsNone(pending_state.load(7, "sesi-1"))

    def test_state_bukan_dict_diabaikan(self):
        with patch(PATCH_GET, return_value="[1, 2]"):
            self.assertIsNone(pending_state.load(7, "sesi-1"))


class TemplatesTests(SimpleTestCase):
    def test_ambiguous_question_format(self):
        text = templates.ambiguous_question(
            [
                _candidate("Kaos Sate Slamet", order="SO-042", tanggal="15 Okt"),
                _candidate("Baju Slametan Anak", order="SO-051", tanggal="17 Okt"),
                _candidate("Pak Slamet", customer="4 order aktif"),
            ]
        )
        lines = text.splitlines()

        self.assertEqual(lines[0], "Ada 3 yang cocok:")
        self.assertIn(
            "(1) Kaos Sate Slamet — order SO-042, tanggal 15 Okt", lines[1]
        )
        self.assertIn("(3) Pak Slamet — customer 4 order aktif", lines[3])
        self.assertEqual(lines[-1], "Yang mana?")

    def test_ambiguous_question_dipotong_ellipsis(self):
        candidates = [
            _candidate(f"Kaos {index}", harga=f"Rp{index + 1}.000")
            for index in range(4)
        ]

        text = templates.ambiguous_question(candidates, max_show=2)

        self.assertIn("(2) Kaos 1", text)
        self.assertIn("... dan 2 lainnya", text)

    def test_ambiguous_question_tanpa_kandidat(self):
        self.assertEqual(
            templates.ambiguous_question([]), "Tidak ada data yang cocok."
        )

    def test_weak_question_ya_tidak(self):
        text = templates.weak_question(_candidate("Kaos Sate", order="SO-042"))

        self.assertEqual(
            text, "Apakah maksud Anda: Kaos Sate — order SO-042? (ya/tidak)"
        )

    def test_weak_question_tanpa_attrs(self):
        self.assertEqual(
            templates.weak_question(_candidate("Kaos Sate")),
            "Apakah maksud Anda: Kaos Sate? (ya/tidak)",
        )

    def test_empty_response_tegas(self):
        self.assertEqual(
            templates.empty_response("order", "Slamet"),
            "Tidak ada order untuk 'Slamet' di data saat ini.",
        )

    def test_out_of_scope_response(self):
        self.assertIn("terlalu singkat", templates.out_of_scope_response())

    def test_escalation_response_daftar_lengkap(self):
        text = templates.escalation_response(
            [_candidate("Kaos A"), _candidate("Kaos B")]
        )

        self.assertIn("(1) Kaos A", text)
        self.assertIn("(2) Kaos B", text)
        self.assertIn("kriteria tambahan", text)


class IntegrasiKlarifikasiTests(SimpleTestCase):
    def test_empty_flow_memberi_jawaban_tegas(self):
        result = classify([], "order Slamet")
        answer = templates.empty_response("order", "Slamet")

        self.assertEqual(result.status, EpistemicStatus.EMPTY)
        self.assertTrue(answer.startswith("Tidak ada order untuk 'Slamet'"))
        self.assertNotIn("maaf", answer.lower())

    def test_ambiguous_flow_menampilkan_tiga_pilihan(self):
        candidates = [
            _candidate("Kaos Sate Slamet", answer_hash="a", order="SO-042"),
            _candidate("Baju Slametan Anak", answer_hash="b", order="SO-051"),
            _candidate("Pak Slamet", answer_hash="c", customer="4 order aktif"),
        ]

        result = classify(candidates, "slamet")
        question = templates.ambiguous_question(result.candidates)

        self.assertEqual(result.status, EpistemicStatus.AMBIGUOUS)
        for index in (1, 2, 3):
            self.assertIn(f"({index})", question)
        self.assertTrue(question.endswith("Yang mana?"))



