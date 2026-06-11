# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMinSellingPriceScaffold(FrappeTestCase):
	def test_child_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Minimum Selling Price Rule"))
		meta = frappe.get_meta("Minimum Selling Price Rule")
		self.assertTrue(meta.istable)
		self.assertEqual(
			{"item_group", "basis", "floor_percent"},
			{df.fieldname for df in meta.fields},
		)


class TestMinSellingPriceSettings(FrappeTestCase):
	def test_settings_fields_exist(self):
		meta = frappe.get_meta("PowerPack Settings")
		names = {df.fieldname for df in meta.fields}
		for fn in (
			"min_selling_price_section",
			"enable_min_selling_price",
			"min_selling_price_default_basis",
			"min_selling_price_default_percent",
			"min_selling_price_override_role",
			"min_selling_price_rules",
		):
			self.assertIn(fn, names)

	def test_feature_flag_toggles(self):
		from cecypo_powerpack.utils import is_feature_enabled

		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		self.assertTrue(is_feature_enabled("enable_min_selling_price"))

		s.enable_min_selling_price = 0
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		self.assertFalse(is_feature_enabled("enable_min_selling_price"))


class TestMinSellingPriceLogic(FrappeTestCase):
	def test_compute_floor_positive(self):
		from cecypo_powerpack.min_selling_price import compute_floor

		self.assertEqual(compute_floor(100, 10, 2), 110.0)

	def test_compute_floor_negative(self):
		from cecypo_powerpack.min_selling_price import compute_floor

		self.assertEqual(compute_floor(100, -10, 2), 90.0)

	def test_pick_rule_exact_match(self):
		from cecypo_powerpack.min_selling_price import pick_rule

		rules = {"Phones": ("Valuation Rate", 10.0)}
		chain = ["Phones", "Electronics", "All Item Groups"]
		self.assertEqual(pick_rule(chain, rules, "Valuation Rate", 0), ("Valuation Rate", 10.0))

	def test_pick_rule_inherits_from_ancestor(self):
		from cecypo_powerpack.min_selling_price import pick_rule

		rules = {"Electronics": ("Last Purchase Rate", -5.0)}
		chain = ["Phones", "Electronics", "All Item Groups"]
		self.assertEqual(pick_rule(chain, rules, "Valuation Rate", 0), ("Last Purchase Rate", -5.0))

	def test_pick_rule_most_specific_wins(self):
		from cecypo_powerpack.min_selling_price import pick_rule

		rules = {"Phones": ("Valuation Rate", 10.0), "Electronics": ("Valuation Rate", 99.0)}
		chain = ["Phones", "Electronics", "All Item Groups"]
		self.assertEqual(pick_rule(chain, rules, "Valuation Rate", 0), ("Valuation Rate", 10.0))

	def test_pick_rule_falls_back_to_default(self):
		from cecypo_powerpack.min_selling_price import pick_rule

		self.assertEqual(pick_rule(["Toys"], {}, "Valuation Rate", 8), ("Valuation Rate", 8.0))

	def test_pick_rule_zero_default_defers(self):
		from cecypo_powerpack.min_selling_price import pick_rule

		self.assertIsNone(pick_rule(["Toys"], {}, "Valuation Rate", 0))
