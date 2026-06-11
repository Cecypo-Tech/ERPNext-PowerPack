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


class TestMinSellingPriceValidation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Item Group tree: _MSP Parent (group) > _MSP Child (leaf, holds items)
		for name, parent, is_group in (("_MSP Parent", "All Item Groups", 1), ("_MSP Child", "_MSP Parent", 0)):
			if not frappe.db.exists("Item Group", name):
				frappe.get_doc({
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": parent,
					"is_group": is_group,
				}).insert()

		from erpnext.stock.doctype.item.test_item import make_item

		make_item("_MSP Item", {"is_stock_item": 1, "item_group": "_MSP Child"})
		# Set cost fields directly so they persist regardless of field read-only rules.
		frappe.db.set_value("Item", "_MSP Item", {"valuation_rate": 100, "last_purchase_rate": 100})
		frappe.clear_cache(doctype="Item")

	def setUp(self):
		# Isolate from native ERPNext check so our feature is the sole authority.
		frappe.db.set_single_value("Selling Settings", "validate_selling_price", 0)

	def _configure(self, enable=1, default_basis="Valuation Rate", default_pct=0,
					override_role=None, rules=None):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = enable
		s.min_selling_price_default_basis = default_basis
		s.min_selling_price_default_percent = default_pct
		s.min_selling_price_override_role = override_role
		s.set("min_selling_price_rules", [])
		for row in (rules or []):
			s.append("min_selling_price_rules", row)
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")

	def _make_so(self, rate):
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		return make_sales_order(item_code="_MSP Item", qty=1, rate=rate, do_not_save=True)

	def test_positive_floor_blocks_below(self):
		# +10% of valuation 100 -> floor 110; rate 105 must be blocked.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		self.assertRaises(frappe.ValidationError, self._make_so(105).save)

	def test_positive_floor_allows_at_or_above(self):
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		so = self._make_so(115)
		so.save()  # must not raise
		self.assertTrue(so.name)

	def test_disabled_feature_does_not_block(self):
		self._configure(enable=0, rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		so = self._make_so(1)
		so.save()  # must not raise
		self.assertTrue(so.name)
