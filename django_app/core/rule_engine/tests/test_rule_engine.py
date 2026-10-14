"""Test `RuleEngine`: operator, fail-closed, priority, batch evaluate."""

from __future__ import annotations

from django.test import TestCase

from core.rule_engine.models import Rule, RuleAction, RuleCondition
from core.rule_engine.services import RuleEngine


class RuleTestMixin:
    """Helper bikin rule/condition/action dengan ringkas."""

    @staticmethod
    def make_rule(code, priority=0, is_active=True):
        return Rule.objects.create(
            code=code, name=code.title(), priority=priority, is_active=is_active
        )

    @staticmethod
    def add_condition(rule, field, operator, value, order=0):
        return RuleCondition.objects.create(
            rule=rule, field=field, operator=operator, value=value, order=order
        )

    @staticmethod
    def add_action(rule, action_type, params=None):
        return RuleAction.objects.create(
            rule=rule, action_type=action_type, params=params or {}
        )


class SingleRuleEvaluationTests(RuleTestMixin, TestCase):
    """evaluate(): operator, AND, fail-closed, dan daftar aksi."""

    def setUp(self):
        self.engine = RuleEngine()

    def test_eq_match_dan_tidak_match(self):
        rule = self.make_rule("EQ_RULE")
        self.add_condition(rule, "order.tag", RuleCondition.Operator.EQ, "FAST_TRACK")

        hasil = self.engine.evaluate("EQ_RULE", {"order": {"tag": "FAST_TRACK"}})
        self.assertTrue(hasil.matched)
        self.assertEqual(hasil.rule, rule)
        self.assertEqual(hasil.reason, "semua kondisi terpenuhi")

        gagal = self.engine.evaluate("EQ_RULE", {"order": {"tag": "EXPORT"}})
        self.assertFalse(gagal.matched)
        self.assertIn("tidak terpenuhi", gagal.reason)

    def test_gt_numerik_termasuk_string_angka(self):
        rule = self.make_rule("GT_RULE")
        self.add_condition(rule, "qty", RuleCondition.Operator.GT, 10)

        self.assertTrue(self.engine.evaluate("GT_RULE", {"qty": 11}).matched)
        self.assertFalse(self.engine.evaluate("GT_RULE", {"qty": 10}).matched)
        # "11" (string dari JSON) tetap dibandingkan sebagai angka.
        self.assertTrue(self.engine.evaluate("GT_RULE", {"qty": "11"}).matched)

    def test_gt_tipe_tidak_cocok_fail_closed(self):
        rule = self.make_rule("GT_TIPE")
        self.add_condition(rule, "qty", RuleCondition.Operator.GT, 10)

        self.assertFalse(self.engine.evaluate("GT_TIPE", {"qty": "banyak"}).matched)

    def test_in_operator(self):
        rule = self.make_rule("IN_RULE")
        self.add_condition(
            rule, "order.tag", RuleCondition.Operator.IN, ["FAST_TRACK", "EXPORT"]
        )

        self.assertTrue(
            self.engine.evaluate("IN_RULE", {"order": {"tag": "EXPORT"}}).matched
        )
        self.assertFalse(
            self.engine.evaluate("IN_RULE", {"order": {"tag": "CUSTOM"}}).matched
        )

    def test_in_value_bukan_list_fail_closed(self):
        rule = self.make_rule("IN_SALAH")
        self.add_condition(rule, "order.tag", RuleCondition.Operator.IN, "FAST_TRACK")

        self.assertFalse(
            self.engine.evaluate("IN_SALAH", {"order": {"tag": "FAST_TRACK"}}).matched
        )

    def test_contains_string_dan_item_list(self):
        rule = self.make_rule("CONTAINS_RULE")
        self.add_condition(
            rule, "note", RuleCondition.Operator.CONTAINS, "urgent", order=0
        )
        self.add_condition(
            rule, "tags", RuleCondition.Operator.CONTAINS, "REWORK", order=1
        )

        cocok = self.engine.evaluate(
            "CONTAINS_RULE", {"note": "kirim urgent ya", "tags": ["REWORK", "QC"]}
        )
        self.assertTrue(cocok.matched)

        gagal = self.engine.evaluate(
            "CONTAINS_RULE", {"note": "biasa", "tags": ["REWORK", "QC"]}
        )
        self.assertFalse(gagal.matched)

    def test_contains_string_case_sensitive(self):
        # CONTAINS = substring apa adanya (case-sensitive); untuk pola fleksibel
        # pakai operator REGEX (yang sudah case-insensitive).
        rule = self.make_rule("CONTAINS_CASE")
        self.add_condition(
            rule, "note", RuleCondition.Operator.CONTAINS, "urgent", order=0
        )

        self.assertFalse(self.engine.evaluate("CONTAINS_CASE", {"note": "URGENT"}).matched)
        self.assertTrue(self.engine.evaluate("CONTAINS_CASE", {"note": "urgent"}).matched)

    def test_regex_match_case_insensitive_dan_pola_invalid(self):
        rule = self.make_rule("REGEX_RULE")
        self.add_condition(rule, "sku", RuleCondition.Operator.REGEX, r"^TS-\d{4}$")

        self.assertTrue(self.engine.evaluate("REGEX_RULE", {"sku": "ts-1234"}).matched)
        self.assertFalse(self.engine.evaluate("REGEX_RULE", {"sku": "TS-12"}).matched)

        rusak = self.make_rule("REGEX_RUSAK")
        self.add_condition(rusak, "sku", RuleCondition.Operator.REGEX, "([")
        self.assertFalse(
            self.engine.evaluate("REGEX_RUSAK", {"sku": "TS-1234"}).matched
        )

    def test_key_tidak_ada_tidak_match_tanpa_exception(self):
        rule = self.make_rule("MISSING_RULE")
        self.add_condition(rule, "bundle.qty", RuleCondition.Operator.EQ, 5)

        hasil = self.engine.evaluate("MISSING_RULE", {"order": {}})
        self.assertFalse(hasil.matched)
        self.assertIn("context tidak punya field 'bundle.qty'", hasil.reason)

    def test_semua_kondisi_harus_match_and(self):
        rule = self.make_rule("AND_RULE")
        self.add_condition(rule, "a", RuleCondition.Operator.EQ, 1, order=0)
        self.add_condition(rule, "b", RuleCondition.Operator.EQ, 2, order=1)

        self.assertTrue(self.engine.evaluate("AND_RULE", {"a": 1, "b": 2}).matched)
        self.assertFalse(self.engine.evaluate("AND_RULE", {"a": 1, "b": 9}).matched)

    def test_rule_tanpa_kondisi_selalu_match(self):
        self.make_rule("KOSONG_RULE")

        hasil = self.engine.evaluate("KOSONG_RULE", {})

        self.assertTrue(hasil.matched)
        self.assertIn("tanpa kondisi", hasil.reason)

    def test_rule_tidak_ada_atau_nonaktif_fail_closed(self):
        tidak_ada = self.engine.evaluate("TIDAK_ADA", {})
        self.assertFalse(tidak_ada.matched)
        self.assertIsNone(tidak_ada.rule)
        self.assertIn("tidak ditemukan", tidak_ada.reason)

        nonaktif = self.make_rule("NONAKTIF", is_active=False)
        self.add_condition(nonaktif, "a", RuleCondition.Operator.EQ, 1)

        hasil = self.engine.evaluate("NONAKTIF", {"a": 1})
        self.assertFalse(hasil.matched)
        self.assertIsNone(hasil.rule)

    def test_operator_tidak_dikenal_fail_closed(self):
        rule = self.make_rule("OP_BOGUS")
        # Nilai di luar TextChoices tetap mungkin ada di DB (mis. hasil import);
        # engine harus aman, bukan crash.
        RuleCondition.objects.create(rule=rule, field="a", operator="BOGUS", value=1)

        hasil = self.engine.evaluate("OP_BOGUS", {"a": 1})
        self.assertFalse(hasil.matched)
        self.assertIn("tidak dikenal", hasil.reason)

    def test_multiple_actions_dikembalikan_sesuai_urutan(self):
        rule = self.make_rule("AKSI_RULE")
        self.add_condition(rule, "qty", RuleCondition.Operator.GT, 0)
        self.add_action(rule, "SET_PRIORITY", {"priority": "HIGH"})
        self.add_action(rule, "TAG_ADD", {"tag": "FAST_TRACK"})
        self.add_action(rule, "ASSIGN_LINE", {"wc_code": "SEWING-1"})

        hasil = self.engine.evaluate("AKSI_RULE", {"qty": 3})

        self.assertEqual(
            [action["action_type"] for action in hasil.actions],
            ["SET_PRIORITY", "TAG_ADD", "ASSIGN_LINE"],
        )
        self.assertEqual(hasil.actions[0]["params"], {"priority": "HIGH"})

    def test_rule_tidak_match_tidak_mengembalikan_aksi(self):
        rule = self.make_rule("AKSI_GAGAL")
        self.add_condition(rule, "qty", RuleCondition.Operator.GT, 10)
        self.add_action(rule, "TAG_ADD", {"tag": "X"})

        hasil = self.engine.evaluate("AKSI_GAGAL", {"qty": 1})
        self.assertFalse(hasil.matched)
        self.assertEqual(hasil.actions, [])


class BatchEvaluationTests(RuleTestMixin, TestCase):
    """evaluate_all(): urutan priority + filter rule_codes."""

    def setUp(self):
        self.engine = RuleEngine()
        self.rule_b = self.make_rule("RULE_B", priority=20)
        self.add_condition(self.rule_b, "qty", RuleCondition.Operator.GT, 100)
        self.rule_a = self.make_rule("RULE_A", priority=10)
        self.add_condition(self.rule_a, "qty", RuleCondition.Operator.GT, 0)
        self.rule_nonaktif = self.make_rule("RULE_OFF", priority=1, is_active=False)
        self.add_condition(self.rule_nonaktif, "qty", RuleCondition.Operator.GT, 0)

    def test_evaluate_all_urut_priority_dan_lewati_nonaktif(self):
        hasil = self.engine.evaluate_all({"qty": 5})

        self.assertEqual([item.rule.code for item in hasil], ["RULE_A", "RULE_B"])
        self.assertEqual([item.matched for item in hasil], [True, False])

    def test_evaluate_all_filter_rule_codes(self):
        hasil = self.engine.evaluate_all({"qty": 5}, rule_codes=["RULE_B"])

        self.assertEqual([item.rule.code for item in hasil], ["RULE_B"])
        self.assertFalse(hasil[0].matched)

    def test_evaluate_all_tanpa_context_key_tidak_error(self):
        hasil = self.engine.evaluate_all({})

        self.assertEqual(len(hasil), 2)
        self.assertTrue(all(not item.matched for item in hasil))
