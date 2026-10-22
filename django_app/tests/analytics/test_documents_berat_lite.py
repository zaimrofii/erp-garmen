"""Test Fase Berat-Lite — pencarian dokumen SOP (TEMPORARY)."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from integrations.analytics.document_search import get_document, search_documents
from integrations.analytics.models import Document


class DocumentSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_documents", stdout=StringIO())

    def test_seed_menghasilkan_delapan_dokumen(self):
        self.assertEqual(Document.objects.count(), 8)

    def test_seed_idempoten(self):
        call_command("seed_documents", stdout=StringIO())

        self.assertEqual(Document.objects.count(), 8)

    def test_dokumen_sop_rework_ada(self):
        self.assertTrue(
            Document.objects.filter(title="SOP Rework Garment", category="SOP").exists()
        )


class DocumentSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_documents", stdout=StringIO())

    def test_search_fulltext_rework(self):
        results = search_documents("rework")

        self.assertTrue(results)
        self.assertTrue(any("Rework" in row["title"] for row in results))

    def test_search_typo_memakai_similarity(self):
        results = search_documents("rewoek")

        self.assertTrue(results)
        self.assertEqual(results[0]["method"], "similarity")

    def test_search_kosong(self):
        self.assertEqual(search_documents("   "), [])

    def test_limit_hasil(self):
        results = search_documents("SOP", limit=2)

        self.assertLessEqual(len(results), 2)

    def test_get_document_dan_none(self):
        document = Document.objects.filter(title="SOP QC").first() or Document.objects.first()

        found = get_document(document.pk)

        self.assertEqual(found["id"], document.pk)
        self.assertIn("title", found)
        self.assertIsNone(get_document(999999))

    def test_hasil_memuat_tags_dan_kategori(self):
        results = search_documents("cutting")

        self.assertTrue(results)
        self.assertIsInstance(results[0]["tags"], list)
        self.assertEqual(results[0]["category"], "SOP")
