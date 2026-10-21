"""Test synonym registry terpusat (FIX #4)."""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator import synonym_registry


class SynonymRegistryTests(SimpleTestCase):
    def test_barang_ke_produk(self):
        self.assertEqual(synonym_registry.get_canonical("barang"), "produk")

    def test_orderan_ke_order(self):
        self.assertEqual(synonym_registry.get_canonical("orderan"), "order")

    def test_mesin_ke_work_center(self):
        self.assertEqual(synonym_registry.get_canonical("mesin"), "work_center")

    def test_kata_tidak_dikenal_none(self):
        self.assertIsNone(synonym_registry.get_canonical("tidak_ada"))

    def test_kata_kosong_none(self):
        self.assertIsNone(synonym_registry.get_canonical(""))
        self.assertIsNone(synonym_registry.get_canonical(None))

    def test_larang_ke_mahal_dan_rewel_ke_rewel(self):
        self.assertEqual(synonym_registry.get_canonical("larang"), "mahal")
        self.assertEqual(synonym_registry.get_canonical("termahal"), "mahal")
        self.assertEqual(synonym_registry.get_canonical("rewel"), "rewel")
        self.assertEqual(synonym_registry.get_canonical("bermasalah"), "rewel")

    def test_royal_dan_boros_dikenali(self):
        self.assertEqual(synonym_registry.get_canonical("royal"), "royal")
        self.assertEqual(synonym_registry.get_canonical("boros"), "boros")
        self.assertEqual(synonym_registry.get_canonical("sultan"), "royal")
        self.assertEqual(synonym_registry.get_canonical("wasteful"), "boros")

    def test_registry_minimal_50_kelompok_dan_100_sinonim(self):
        total_synonyms = sum(
            len(values) for values in synonym_registry.SYNONYM_MAP.values()
        )
        self.assertGreaterEqual(len(synonym_registry.SYNONYM_MAP), 50)
        self.assertGreaterEqual(total_synonyms, 100)

    def test_setiap_sinonim_punya_reverse_mapping(self):
        for canonical, synonyms in synonym_registry.SYNONYM_MAP.items():
            self.assertEqual(synonym_registry.get_canonical(canonical), canonical)
            for synonym in synonyms:
                self.assertEqual(
                    synonym_registry.get_canonical(synonym),
                    canonical,
                    msg=f"{synonym!r} harus → {canonical!r}",
                )

    def test_expand_keywords_menambah_kanonik_dan_sinonim(self):
        expanded = synonym_registry.expand_keywords(["barang"])

        self.assertIn("produk", expanded)
        self.assertIn("barang", expanded)
        self.assertIn("sku", expanded)


class FollowupMetadataTests(SimpleTestCase):
    def test_followup_dan_rank_terdaftar(self):
        self.assertIn("kedua", synonym_registry.FOLLOWUP_CANONICALS)
        self.assertIn("kemarin", synonym_registry.FOLLOWUP_CANONICALS)
        self.assertEqual(synonym_registry.RANK_CANONICALS[2], "kedua")

    def test_entity_produk_dan_order(self):
        self.assertEqual(synonym_registry.ENTITY_CANONICALS["produk"], "product")
        self.assertEqual(synonym_registry.ENTITY_CANONICALS["order"], "order")
