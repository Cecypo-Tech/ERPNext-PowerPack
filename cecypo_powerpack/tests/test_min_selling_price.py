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
			"min_selling_price_whole_sale",
			"min_selling_price_rules",
		):
			self.assertIn(fn, names)

	def test_whole_sale_field_is_a_checkbox_after_the_pricing_rule_skip(self):
		meta = frappe.get_meta("PowerPack Settings")
		df = meta.get_field("min_selling_price_whole_sale")
		self.assertEqual(df.fieldtype, "Check")
		self.assertEqual(df.default, "0")
		order = [f.fieldname for f in meta.fields]
		self.assertEqual(
			order.index("min_selling_price_whole_sale"),
			order.index("min_selling_price_skip_if_pricing_rule") + 1,
		)

	def test_help_text_states_the_real_semantics(self):
		# A zero row is dropped from the rules, so its group takes the global default;
		# only a zero global default defers to ERPNext. And ERPNext's own check must be
		# off whenever this feature is on, not only for negative floors, because it
		# also enforces the last purchase rate.
		note = frappe.get_meta("PowerPack Settings").get_field("min_selling_price_description").options
		self.assertIn("global default applies", note)
		self.assertIn("whenever this is enabled", note)
		self.assertIn("last purchase rate", note)
		self.assertNotIn("If using negative values", note)
		row_help = frappe.get_meta("Minimum Selling Price Rule").get_field("floor_percent").description
		self.assertIn("global default applies", row_help)
		self.assertNotIn("defer to ERPNext", row_help)

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
		# item_group is forced for a different reason: make_item only applies its
		# arguments when it *creates* the item, so an item left behind by an earlier
		# run keeps whatever group it had. Every rule here is scoped to the _MSP
		# groups, so the wrong group takes them all out of play - the blocking tests
		# fail, and the "allows" tests pass without anything having been enforced.
		frappe.db.set_value(
			"Item",
			"_MSP Item",
			{"item_group": "_MSP Child", "valuation_rate": 100, "last_purchase_rate": 100},
		)
		# A second item whose master valuation_rate stays blank: its only cost
		# source is the Bin, which the stock entry below seeds at 100.
		make_item("_MSP Bin Item", {"is_stock_item": 1, "item_group": "_MSP Child"})
		frappe.db.set_value(
			"Item", "_MSP Bin Item", {"item_group": "_MSP Child", "valuation_rate": 0, "last_purchase_rate": 0}
		)
		if not frappe.db.exists("Bin", {"item_code": "_MSP Bin Item", "warehouse": "_Test Warehouse - _TC"}):
			from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

			make_stock_entry(item_code="_MSP Bin Item", target="_Test Warehouse - _TC", qty=10, rate=100)
		# A second leaf group so whole-sale tests can mix an override group with a
		# global-default group in one document. Same cost (100) as _MSP Item.
		if not frappe.db.exists("Item Group", "_MSP Loss Group"):
			frappe.get_doc({
				"doctype": "Item Group",
				"item_group_name": "_MSP Loss Group",
				"parent_item_group": "_MSP Parent",
				"is_group": 0,
			}).insert()
		make_item("_MSP Loss Item", {"is_stock_item": 1, "item_group": "_MSP Loss Group"})
		frappe.db.set_value(
			"Item",
			"_MSP Loss Item",
			{"item_group": "_MSP Loss Group", "valuation_rate": 100, "last_purchase_rate": 100},
		)
		# All of the above was created after the base class flushed its own test
		# records, so it is still uncommitted. tearDown rolls back after every test,
		# which would otherwise take the item groups with it.
		frappe.db.commit()
		frappe.clear_cache(doctype="Item")

	def setUp(self):
		# Isolate from native ERPNext check so our feature is the sole authority.
		frappe.db.set_single_value("Selling Settings", "validate_selling_price", 0)

	def _configure(self, enable=1, default_basis="Valuation Rate", default_pct=0,
					override_role=None, rules=None, whole_sale=0):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = enable
		s.min_selling_price_default_basis = default_basis
		s.min_selling_price_default_percent = default_pct
		s.min_selling_price_override_role = override_role
		s.min_selling_price_whole_sale = whole_sale
		s.set("min_selling_price_rules", [])
		for row in (rules or []):
			s.append("min_selling_price_rules", row)
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")

	def _make_so(self, rate):
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		return make_sales_order(item_code="_MSP Item", qty=1, rate=rate, do_not_save=True)

	def _make_two_row_so(self, rate_a, rate_b, item_b="_MSP Loss Item"):
		"""Row 1: _MSP Item (group _MSP Child) at rate_a. Row 2: item_b at rate_b. Both cost 100."""
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		return make_sales_order(
			do_not_save=True,
			item_list=[
				{"item_code": "_MSP Item", "warehouse": "_Test Warehouse - _TC", "qty": 1, "rate": rate_a},
				{"item_code": item_b, "warehouse": "_Test Warehouse - _TC", "qty": 1, "rate": rate_b},
			],
		)

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

		# The rate is below the floor, so the rule has something to act on. Totals
		# are computed here, as Administrator, because saving the order as the test
		# user is not a property of the rule under test: on a bench running ERPNext
		# Express the customer's Address is readable only by Express roles, and that
		# app forbids an Express user from holding any other role - so no user could
		# hold the override role and still save the order. Calling the rule directly
		# keeps this test about the override, not about the other apps installed.
		from cecypo_powerpack.min_selling_price import validate_min_selling_price

		so = self._make_so(105)
		so.run_method("set_missing_values")
		so.calculate_taxes_and_totals()

		frappe.set_user(test_user)
		try:
			# Must not raise: the floor is breached, but the role may override it.
			validate_min_selling_price(so)
		finally:
			frappe.set_user("Administrator")

		# Guard against a vacuous pass. If the order did not actually breach the
		# floor, the call above would be silent for the wrong reason - so the same
		# order, with no override role configured, must be blocked.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		self.assertRaises(frappe.ValidationError, validate_min_selling_price, so)

	def test_judged_rows_reports_whether_the_rule_is_an_override(self):
		# _MSP Child has an override; a row in a group with no override falls to the
		# global default and must be reported as has_override=False. Rows with no
		# rule at all, free rows and pricing-rule rows never come out.
		from cecypo_powerpack.min_selling_price import _build_rules, _judged_rows

		self._configure(default_pct=4, rules=[
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -20},
		])
		settings = frappe.get_cached_doc("PowerPack Settings")
		rules = _build_rules(settings)
		rows = [
			frappe._dict({"item_code": "_MSP Item", "item_group": "_MSP Child", "idx": 1, "conversion_factor": 1}),
			frappe._dict({"item_code": "_MSP Item", "item_group": "All Item Groups", "idx": 2, "conversion_factor": 1}),
			frappe._dict({"item_code": "_MSP Item", "item_group": "_MSP Child", "idx": 3, "is_free_item": 1}),
			frappe._dict({"item_code": "", "idx": 4}),
		]
		doc = frappe._dict({"doctype": "Sales Order", "items": rows})
		out = list(_judged_rows(doc, settings, rules, "Valuation Rate", 4.0))
		self.assertEqual([(r.idx, rule, ov) for r, rule, ov in out], [
			(1, ("Valuation Rate", -20.0), True),
			(2, ("Valuation Rate", 4.0), False),
		])

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

	def _make_pos_invoice(self, rate):
		# Built by hand: erpnext's make_pos_profile() starts with
		# `delete from tabPOS Profile`, which is not something to run on a real site.
		profile_name = "_MSP POS Profile"
		if not frappe.db.exists("POS Profile", profile_name):
			profile = frappe.get_doc({
				"doctype": "POS Profile",
				"name": profile_name,
				"company": "_Test Company",
				"cost_center": "_Test Cost Center - _TC",
				"currency": "INR",
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"income_account": "Sales - _TC",
				"selling_price_list": "_Test Price List",
				"territory": "_Test Territory",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"warehouse": "_Test Warehouse - _TC",
				"write_off_account": "_Test Write Off - _TC",
				"write_off_cost_center": "_Test Write Off Cost Center - _TC",
				"payments": [{"mode_of_payment": "Cash", "default": 1}],
			})
			profile.insert()
		else:
			profile = frappe.get_doc("POS Profile", profile_name)
		# A cashier can hold only one open shift site-wide, so use a dedicated one.
		cashier = "_msp_cashier@example.com"
		if not frappe.db.exists("User", cashier):
			frappe.get_doc({
				"doctype": "User", "email": cashier, "first_name": "MSP Cashier", "send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("POS Opening Entry", {"pos_profile": profile_name, "status": "Open"}):
			from erpnext.accounts.doctype.pos_opening_entry.test_pos_opening_entry import create_opening_entry

			create_opening_entry(profile, cashier)

		pos = frappe.new_doc("POS Invoice")
		pos.update({
			"is_pos": 1, "update_stock": 1, "pos_profile": profile_name,
			"company": "_Test Company", "customer": "_Test Customer", "debit_to": "Debtors - _TC",
			"currency": "INR", "conversion_rate": 1, "account_for_change_amount": "Cash - _TC",
		})
		pos.set_missing_values()
		pos.append("items", {
			"item_code": "_MSP Bin Item", "warehouse": "_Test Warehouse - _TC", "qty": 1, "rate": rate,
			"income_account": "Sales - _TC", "expense_account": "Cost of Goods Sold - _TC",
			"cost_center": "_Test Cost Center - _TC",
		})
		return pos

	def test_pos_invoice_uses_bin_valuation_when_row_has_no_incoming_rate(self):
		# POS Invoice rows never carry incoming_rate at validate time, and the item
		# master valuation is blank, so the only cost source is the Bin.
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		with self.assertRaisesRegex(frappe.ValidationError, "at least"):
			self._make_pos_invoice(105).save()

	def test_pos_invoice_bin_fallback_allows_at_or_above_floor(self):
		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		pos = self._make_pos_invoice(110)
		pos.save()  # must not raise
		self.assertTrue(pos.name)

	def test_non_stock_sales_invoice_uses_bin_valuation(self):
		# Sales Invoice without Update Stock: same gap as POS Invoice.
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		si = create_sales_invoice(item_code="_MSP Bin Item", qty=1, rate=105, update_stock=0, do_not_save=True)
		with self.assertRaisesRegex(frappe.ValidationError, "at least"):
			si.save()

	def test_non_stock_sales_invoice_bin_fallback_allows_at_or_above_floor(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		si = create_sales_invoice(item_code="_MSP Bin Item", qty=1, rate=110, update_stock=0, do_not_save=True)
		si.save()  # must not raise
		self.assertTrue(si.name)

	# ---- whole-sale mode -------------------------------------------------------
	# Both items cost 100. Global floor 4% => a two-row sale needs net >= 208.

	def test_whole_sale_allows_a_loss_row_covered_by_another(self):
		# Row 1 at 90 (below cost), row 2 at 130: total 220 >= 208. Per-item mode
		# would block row 1; whole-sale mode must accept the sale.
		self._configure(default_pct=4, whole_sale=1)
		so = self._make_two_row_so(90, 130)
		so.save()  # must not raise
		self.assertTrue(so.name)

	def test_per_item_mode_still_blocks_the_same_loss_row(self):
		self._configure(default_pct=4, whole_sale=0)
		with self.assertRaisesRegex(frappe.ValidationError, r"Row #1 .*at least"):
			self._make_two_row_so(90, 130).save()

	def test_whole_sale_blocks_when_the_total_is_short(self):
		# 90 + 110 = 200 < 208. The message names the sale floor, not any row.
		self._configure(default_pct=4, whole_sale=1)
		with self.assertRaisesRegex(frappe.ValidationError, r"Net total of this sale should be at least"):
			self._make_two_row_so(90, 110).save()

	def test_whole_sale_accepts_exactly_the_floor(self):
		self._configure(default_pct=4, whole_sale=1)
		so = self._make_two_row_so(100, 108)  # 208 == 208
		so.save()
		self.assertTrue(so.name)

	def test_whole_sale_override_row_is_a_guardrail(self):
		# _MSP Child may go to -20% (floor 80). Row 1 at 85 is within it and the
		# sale total 85 + 130 = 215 >= 208, so it passes. Row 1 at 75 breaches the
		# guardrail even though 75 + 140 = 215 still clears the sale floor.
		self._configure(default_pct=4, whole_sale=1, rules=[
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -20},
		])
		so = self._make_two_row_so(85, 130)
		so.save()
		self.assertTrue(so.name)
		with self.assertRaisesRegex(frappe.ValidationError, r"Row #1 .*at least"):
			self._make_two_row_so(75, 140).save()

	def test_whole_sale_positive_override_still_forces_margin_on_its_group(self):
		# _MSP Child must make +10% (floor 110). Row 1 at 105 fails even though
		# 105 + 150 = 255 clears the sale floor of 208.
		self._configure(default_pct=4, whole_sale=1, rules=[
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10},
		])
		with self.assertRaisesRegex(frappe.ValidationError, r"Row #1 .*at least"):
			self._make_two_row_so(105, 150).save()

	def test_whole_sale_row_without_override_is_not_judged_alone(self):
		# Only _MSP Child has an override. _MSP Loss Item (no override) at 60 is
		# fine on its own as long as the sale clears 208: 150 + 60 = 210.
		self._configure(default_pct=4, whole_sale=1, rules=[
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10},
		])
		so = self._make_two_row_so(150, 60)
		so.save()
		self.assertTrue(so.name)

	def test_whole_sale_with_zero_global_has_no_sale_gate(self):
		# Global 0: nothing gates the total. The override on _MSP Child is the only
		# rule, so row 2 at 10 is untouched and row 1 at 95 (within -20%) passes.
		self._configure(default_pct=0, whole_sale=1, rules=[
			{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": -20},
		])
		so = self._make_two_row_so(95, 10)
		so.save()
		self.assertTrue(so.name)

	def test_whole_sale_zero_cost_row_is_left_out_of_both_sides(self):
		# A row whose cost resolves to 0 cannot be judged, so it must neither add to
		# the required total nor pad the actual total. Direct call with hand-built
		# rows: row 2 has no cost and a huge net amount; row 1 alone is short.
		from cecypo_powerpack.min_selling_price import validate_min_selling_price

		self._configure(default_pct=4, whole_sale=1)
		rows = [
			frappe._dict({
				"item_code": "_MSP Item", "item_name": "_MSP Item", "item_group": "_MSP Child", "idx": 1,
				"qty": 1, "conversion_factor": 1, "valuation_rate": 100,
				"base_net_rate": 100, "base_net_amount": 100,
				"precision": lambda *_: 2,
			}),
			frappe._dict({
				"item_code": "_MSP Item", "item_name": "_MSP Item", "item_group": "_MSP Child", "idx": 2,
				"qty": 1, "conversion_factor": 1, "valuation_rate": 0, "warehouse": "_MSP No Such Warehouse",
				"base_net_rate": 9999, "base_net_amount": 9999,
				"precision": lambda *_: 2,
			}),
		]
		doc = frappe._dict({
			"doctype": "Sales Order", "company": "_Test Company", "items": rows,
			"precision": lambda *_: 2,
		})
		frappe.db.set_value("Item", "_MSP Item", "valuation_rate", 0)
		try:
			with self.assertRaisesRegex(frappe.ValidationError, r"Net total of this sale should be at least"):
				validate_min_selling_price(doc)
		finally:
			frappe.db.set_value("Item", "_MSP Item", "valuation_rate", 100)
			frappe.clear_cache(doctype="Item")

	def test_whole_sale_override_role_warns_instead_of_blocking(self):
		# Same arrangement as test_override_role_allows_save: the rule is called
		# directly as the override user so this stays about the role, not about
		# whether that user may save a Sales Order on this bench.
		from cecypo_powerpack.min_selling_price import validate_min_selling_price

		role = "_MSP Override Role"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		test_user = "msp_override@example.com"
		if not frappe.db.exists("User", test_user):
			frappe.get_doc({
				"doctype": "User", "email": test_user, "first_name": "MSP",
				"roles": [{"role": role}, {"role": "Sales User"}, {"role": "System Manager"}],
			}).insert()
		self._configure(default_pct=4, whole_sale=1, override_role=role)
		so = self._make_two_row_so(90, 110)  # 200 < 208
		so.run_method("set_missing_values")
		so.calculate_taxes_and_totals()
		frappe.set_user(test_user)
		try:
			validate_min_selling_price(so)  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_delivery_note_enforced(self):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		self._configure(rules=[{"item_group": "_MSP Child", "basis": "Valuation Rate", "floor_percent": 10}])
		dn = create_delivery_note(item_code="_MSP Item", qty=1, rate=105, do_not_save=True)
		self.assertRaises(frappe.ValidationError, dn.save)


class TestPowerPackSettingsTabs(FrappeTestCase):
	# Kept in step with the shipped doctype JSON. pricing_tab was added after this
	# test was written, so the assertion named a tab order the app no longer had.
	EXPECTED_TABS = ["appearance_tab", "sales_pos_tab", "pricing_tab", "items_tab", "system_tab"]

	def test_tabs_present_in_order(self):
		meta = frappe.get_meta("PowerPack Settings")
		tab_order = [df.fieldname for df in meta.fields if df.fieldtype == "Tab Break"]
		self.assertEqual(tab_order, self.EXPECTED_TABS)

	def test_no_fields_lost_and_new_section_in_sales_tab(self):
		import json
		import os

		import cecypo_powerpack

		path = os.path.join(
			os.path.dirname(cecypo_powerpack.__file__),
			"cecypo_powerpack", "doctype", "powerpack_settings", "powerpack_settings.json",
		)
		d = json.load(open(path))
		fo = d["field_order"]
		# No duplicates; field_order matches fields set.
		self.assertEqual(len(fo), len(set(fo)))
		self.assertEqual(set(fo), {f["fieldname"] for f in d["fields"]})
		# A representative field from every original section still present.
		for fn in ("enable_compact_theme", "enable_pos_powerup", "enable_quick_pay",
				   "enable_min_selling_price", "enable_lens", "enable_item_list_powerup",
				   "enable_payment_reconciliation_powerup", "prevent_etr_invoice_cancellation"):
			self.assertIn(fn, fo)
		# Min Selling Price section sits between the Sales & POS tab and the Items tab.
		i_sales = fo.index("sales_pos_tab")
		i_items = fo.index("items_tab")
		self.assertLess(i_sales, fo.index("min_selling_price_section"))
		self.assertLess(fo.index("min_selling_price_section"), i_items)
