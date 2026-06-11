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

	def test_negative_floor_allows_below_cost_within_tolerance(self):
		# -10% of valuation 100 -> floor 90; rate 95 is below cost but allowed.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -10}])
		so = self._make_so(95)
		so.save()  # must not raise
		self.assertTrue(so.name)

	def test_negative_floor_blocks_below_tolerance(self):
		# -10% -> floor 90; rate 85 is below the floor and must be blocked.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -10}])
		self.assertRaises(frappe.ValidationError, self._make_so(85).save)

	def test_zero_percent_rule_defers(self):
		# 0% rule is ignored -> with native off, nothing blocks even at rate 1.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 0}])
		so = self._make_so(1)
		so.save()
		self.assertTrue(so.name)

	def test_tree_inheritance_from_parent(self):
		# Rule on parent group applies to item in child group.
		self._configure(rules=[{"item_group": "_MSP Parent", "basis": "Valuation Rate", "floor_percent": 10}])
		self.assertRaises(frappe.ValidationError, self._make_so(105).save)

	def test_child_rule_overrides_parent(self):
		# Parent +50% (floor 150) but child -10% (floor 90); rate 95 allowed.
		self._configure(rules=[
			{"item_group": "_MSP Parent", "basis": "Valuation Rate", "floor_percent": 50},
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -10},
		])
		so = self._make_so(95)
		so.save()
		self.assertTrue(so.name)

	def test_global_default_applies_without_rule(self):
		self._configure(default_basis="Valuation Rate", default_pct=10, rules=[])
		self.assertRaises(frappe.ValidationError, self._make_so(105).save)

	def test_last_purchase_rate_basis(self):
		# last_purchase_rate 100, +10% -> floor 110; rate 105 blocked.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Last Purchase Rate", "floor_percent": 10}])
		self.assertRaises(frappe.ValidationError, self._make_so(105).save)

	def test_override_role_allows_save(self):
		role = "_MSP Override Role"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		test_user = "msp_override@example.com"
		if not frappe.db.exists("User", test_user):
			user = frappe.get_doc({
				"doctype": "User", "email": test_user, "first_name": "MSP",
				"roles": [{"role": role}, {"role": "Sales User"}, {"role": "System Manager"}],
			})
			user.insert()
		self._configure(override_role=role,
						rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		frappe.set_user(test_user)
		try:
			so = self._make_so(105)
			so.save()  # below floor, but override role -> allowed
			self.assertTrue(so.name)
		finally:
			frappe.set_user("Administrator")

	def test_free_item_skipped(self):
		# Direct call with a free-item line: our validation must skip it (no raise).
		from cecypo_powerpack.min_selling_price import validate_min_selling_price

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		item = frappe._dict({
			"item_code": "_MSP Item", "item_name": "_MSP Item", "item_group": "_MSP Child",
			"idx": 1, "is_free_item": 1, "base_net_rate": 0, "conversion_factor": 1,
		})
		validate_min_selling_price(frappe._dict({"doctype": "Sales Order", "items": [item]}))

	def test_returns_and_internal_customers_skipped(self):
		# Both flags make the validation return early before touching any line.
		from cecypo_powerpack.min_selling_price import validate_min_selling_price

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		item = frappe._dict({
			"item_code": "_MSP Item", "item_name": "_MSP Item", "item_group": "_MSP Child",
			"idx": 1, "base_net_rate": 1, "conversion_factor": 1,
		})
		validate_min_selling_price(frappe._dict({"doctype": "Sales Invoice", "is_return": 1, "items": [item]}))
		validate_min_selling_price(frappe._dict({"doctype": "Sales Invoice", "is_internal_customer": 1, "items": [item]}))

	def test_all_target_doctypes_wired(self):
		from cecypo_powerpack.min_selling_price import TARGET_DOCTYPES

		handler = "cecypo_powerpack.min_selling_price.validate_min_selling_price"
		doc_events = frappe.get_hooks("doc_events")
		for dt in TARGET_DOCTYPES:
			validators = (doc_events.get(dt) or {}).get("validate") or []
			self.assertIn(handler, validators, f"{dt} not wired")

	def test_delivery_note_enforced(self):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		dn = create_delivery_note(item_code="_MSP Item", qty=1, rate=105, do_not_save=True)
		self.assertRaises(frappe.ValidationError, dn.save)
