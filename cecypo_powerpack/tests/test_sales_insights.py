# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase

COMPANY = "_Test Company"
WH = "_Test Warehouse - _TC"
WH2 = "_Test Warehouse 1 - _TC"
CUSTOMER = "_Test Customer"
OTHER_CUSTOMER = "_Test Customer 1"
SETTINGS_CACHE_KEYS = ("powerpack_settings", "powerpack_feature_enable_quotation_powerup")


def _code(is_stock_item=1):
	code = "_PP-INS-" + frappe.generate_hash(length=8)
	frappe.get_doc({
		"doctype": "Item",
		"item_code": code,
		"item_group": "All Item Groups",
		"stock_uom": "Nos",
		"is_stock_item": is_stock_item,
	}).insert(ignore_permissions=True)
	return code


def _bin(item_code, warehouse, actual_qty, valuation_rate, reserved_qty=0):
	frappe.get_doc({
		"doctype": "Bin",
		"name": frappe.generate_hash(length=10),
		"item_code": item_code,
		"warehouse": warehouse,
		"actual_qty": actual_qty,
		"reserved_qty": reserved_qty,
		"projected_qty": actual_qty - reserved_qty,
		"valuation_rate": valuation_rate,
		"stock_value": actual_qty * valuation_rate,
	}).db_insert()


def _invoice(doctype, posting_date, item_code, base_net_rate, conversion_factor=1, is_return=0,
			 party=None, docstatus=1, company=COMPANY, posting_time="10:00:00"):
	"""A submitted invoice row written straight to the tables. The code under test is a
	query over these tables, so running ERPNext's whole posting path would only add setup."""
	parent = frappe.get_doc({
		"doctype": doctype,
		"name": frappe.generate_hash(length=10),
		"company": company,
		"posting_date": posting_date,
		"posting_time": posting_time,
		"docstatus": docstatus,
		"is_return": is_return,
		("customer" if doctype == "Sales Invoice" else "supplier"): party,
	})
	parent.db_insert()
	frappe.get_doc({
		"doctype": doctype + " Item",
		"name": frappe.generate_hash(length=10),
		"parent": parent.name,
		"parenttype": doctype,
		"parentfield": "items",
		"idx": 1,
		"docstatus": docstatus,
		"item_code": item_code,
		"qty": 1,
		"conversion_factor": conversion_factor,
		"base_net_rate": base_net_rate,
		"rate": base_net_rate,
	}).db_insert()
	return parent.name


class TestSalesItemInsights(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("PowerPack Settings", {
			"enable_quotation_powerup": 1,
			"sales_visible_to_role": "System Manager",
		})
		self._clear_settings_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._clear_settings_cache()

	def _clear_settings_cache(self):
		frappe.clear_cache(doctype="PowerPack Settings")
		for key in SETTINGS_CACHE_KEYS:
			frappe.cache().delete_value(key)

	def _call(self, pairs, customer=None, doctype="Quotation", company=COMPANY):
		from cecypo_powerpack.sales_insights import get_sales_item_insights

		items = json.dumps([{"item_code": c, "warehouse": w} for c, w in pairs])
		return get_sales_item_insights(doctype=doctype, items=items, customer=customer, company=company)

	def _one(self, item_code, warehouse=WH, customer=None):
		res = self._call([(item_code, warehouse)], customer=customer)
		self.assertEqual(len(res["items"]), 1)
		return res, res["items"][0]

	def test_stock_and_valuation_from_the_warehouse_bin(self):
		code = _code()
		_bin(code, WH, actual_qty=10, valuation_rate=40, reserved_qty=3)
		res, row = self._one(code)
		self.assertTrue(res["can_see_cost"])
		self.assertEqual(row["actual_qty"], 10)
		self.assertEqual(row["reserved_qty"], 3)
		self.assertEqual(row["available_qty"], 7)
		self.assertEqual(row["valuation_rate"], 40)

	def test_valuation_falls_back_to_weighted_company_bins(self):
		# Nothing in the chosen warehouse still has a known cost elsewhere; weighting by
		# qty (not a plain AVG over bins) is what the stock ledger would say.
		code = _code()
		_bin(code, WH2, actual_qty=1, valuation_rate=10)
		_bin(code, "Finished Goods - _TC", actual_qty=3, valuation_rate=30)
		_, row = self._one(code, warehouse=WH)
		self.assertEqual(row["actual_qty"], 0)
		self.assertAlmostEqual(row["valuation_rate"], 25)

	def test_no_warehouse_sums_stock_across_company_bins(self):
		code = _code()
		_bin(code, WH, actual_qty=2, valuation_rate=10)
		_bin(code, WH2, actual_qty=2, valuation_rate=30)
		_, row = self._one(code, warehouse=None)
		self.assertEqual(row["actual_qty"], 4)
		self.assertAlmostEqual(row["valuation_rate"], 20)

	def test_other_company_bins_are_ignored(self):
		other_wh = frappe.db.get_value("Warehouse", {"company": ("!=", COMPANY), "is_group": 0}, "name")
		code = _code()
		_bin(code, other_wh, actual_qty=100, valuation_rate=999)
		_, row = self._one(code, warehouse=None)
		self.assertEqual(row["actual_qty"], 0)
		self.assertIsNone(row["valuation_rate"])

	def test_last_purchase_is_per_stock_uom_and_skips_returns_and_drafts(self):
		code = _code()
		_invoice("Purchase Invoice", "2026-01-01", code, base_net_rate=50, party="_Test Supplier")
		# a Box of 12 at 1200 is 100 per stock unit
		_invoice("Purchase Invoice", "2026-02-01", code, base_net_rate=1200, conversion_factor=12,
				 party="_Test Supplier")
		_invoice("Purchase Invoice", "2026-03-01", code, base_net_rate=999, is_return=1, party="_Test Supplier")
		_invoice("Purchase Invoice", "2026-04-01", code, base_net_rate=999, docstatus=0, party="_Test Supplier")
		_, row = self._one(code)
		self.assertAlmostEqual(row["last_purchase_rate"], 100)
		self.assertEqual(str(row["last_purchase_date"]), "2026-02-01")

	def test_same_day_purchases_resolve_by_posting_time(self):
		code = _code()
		_invoice("Purchase Invoice", "2026-02-01", code, base_net_rate=70, party="_Test Supplier",
				 posting_time="15:00:00")
		_invoice("Purchase Invoice", "2026-02-01", code, base_net_rate=60, party="_Test Supplier",
				 posting_time="09:00:00")
		_, row = self._one(code)
		self.assertAlmostEqual(row["last_purchase_rate"], 70)

	def test_last_sale_and_last_sale_to_customer(self):
		code = _code()
		_invoice("Sales Invoice", "2026-01-10", code, base_net_rate=240, conversion_factor=2, party=CUSTOMER)
		_invoice("Sales Invoice", "2026-02-10", code, base_net_rate=150, party=OTHER_CUSTOMER)
		_, row = self._one(code, customer=CUSTOMER)
		self.assertAlmostEqual(row["last_sale_rate"], 150)
		self.assertEqual(str(row["last_sale_date"]), "2026-02-10")
		self.assertAlmostEqual(row["last_sale_to_customer_rate"], 120)
		self.assertEqual(str(row["last_sale_to_customer_date"]), "2026-01-10")

	def test_other_company_history_is_ignored(self):
		# base_net_rate is in each company's own currency, so mixing companies would
		# compare, say, KES with USD.
		other = frappe.db.get_value("Company", {"name": ("!=", COMPANY)}, "name")
		if not other:
			self.skipTest("needs a second company")
		code = _code()
		_invoice("Sales Invoice", "2026-02-10", code, base_net_rate=5, party=CUSTOMER, company=other)
		_, row = self._one(code)
		self.assertIsNone(row["last_sale_rate"])

	def test_non_stock_item_has_no_stock_or_cost(self):
		code = _code(is_stock_item=0)
		_, row = self._one(code)
		self.assertIsNone(row["actual_qty"])
		self.assertIsNone(row["valuation_rate"])

	def test_many_items_in_one_call(self):
		codes = [_code() for _ in range(3)]
		for i, code in enumerate(codes):
			_bin(code, WH, actual_qty=i + 1, valuation_rate=10 * (i + 1))
		res = self._call([(c, WH) for c in codes] + [(codes[0], WH)])
		by_code = {r["item_code"]: r for r in res["items"]}
		self.assertEqual(set(by_code), set(codes))
		self.assertEqual(by_code[codes[2]]["valuation_rate"], 30)

	def test_cost_fields_withheld_from_users_without_the_role(self):
		code = _code()
		_bin(code, WH, actual_qty=5, valuation_rate=40)
		_invoice("Purchase Invoice", "2026-02-01", code, base_net_rate=35, party="_Test Supplier")
		_invoice("Sales Invoice", "2026-02-10", code, base_net_rate=90, party=CUSTOMER)
		frappe.db.set_single_value("PowerPack Settings", "sales_visible_to_role", "Accounts Manager")
		self._clear_settings_cache()
		user = self._user(["Sales User"])
		self.assertNotIn("Accounts Manager", frappe.get_roles(user))
		frappe.set_user(user)
		res, row = self._one(code)
		self.assertFalse(res["can_see_cost"])
		self.assertIsNone(row["valuation_rate"])
		self.assertIsNone(row["last_purchase_rate"])
		self.assertIsNone(row["last_purchase_date"])
		# stock and sales history are not cost data
		self.assertEqual(row["actual_qty"], 5)
		self.assertAlmostEqual(row["last_sale_rate"], 90)

	def _user(self, roles, user_type="System User", company_permission=None):
		user = frappe.get_doc({
			"doctype": "User",
			"email": f"pp-insights-{frappe.generate_hash(length=6)}@example.com",
			"first_name": "Insights Test",
			"user_type": user_type,
			"send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}).insert(ignore_permissions=True)
		if company_permission:
			frappe.get_doc({
				"doctype": "User Permission", "user": user.name, "allow": "Company",
				"for_value": company_permission, "apply_to_all_doctypes": 1,
			}).insert(ignore_permissions=True)
		return user.name

	def test_portal_users_are_refused(self):
		code = _code()
		frappe.set_user(self._user(["Customer"], user_type="Website User"))
		with self.assertRaises(frappe.PermissionError):
			self._call([(code, WH)], customer=CUSTOMER)

	def test_users_without_read_on_the_doctype_are_refused(self):
		code = _code()
		frappe.set_user(self._user(["Stock User"]))
		with self.assertRaises(frappe.PermissionError):
			self._call([(code, WH)])

	def test_a_user_limited_to_another_company_is_refused(self):
		other = frappe.db.get_value("Company", {"name": ("!=", COMPANY)}, "name")
		code = _code()
		frappe.set_user(self._user(["Sales User"], company_permission=other))
		with self.assertRaises(frappe.PermissionError):
			self._call([(code, WH)], company=COMPANY)

	def test_company_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			self._call([(_code(), WH)], company=None)

	def test_disabled_doctype_is_refused(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_sales_order_powerup", 0)
		self._clear_settings_cache()
		with self.assertRaises(frappe.PermissionError):
			self._call([(_code(), WH)], doctype="Sales Order")

	def test_unknown_doctype_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self._call([(_code(), WH)], doctype="Purchase Order")

	def test_old_unguarded_endpoint_is_gone(self):
		import cecypo_powerpack.api as api

		self.assertFalse(hasattr(api, "get_item_info_for_quotation"))


class TestMarginBandSettings(FrappeTestCase):
	FIELDS = ("sales_margin_low_below", "sales_margin_medium_below", "sales_margin_good_below")

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="PowerPack Settings")

	def test_patch_seeds_defaults_only_where_never_set(self):
		from cecypo_powerpack.patches.v1.default_sales_margin_bands import execute

		frappe.db.sql(
			"delete from `tabSingles` where doctype='PowerPack Settings' and field in %s", (self.FIELDS,)
		)
		frappe.db.set_single_value("PowerPack Settings", "sales_margin_good_below", 50)
		execute()
		values = [frappe.db.get_single_value("PowerPack Settings", f) for f in self.FIELDS]
		self.assertEqual(values, [10, 20, 50])

	def test_bands_must_rise(self):
		doc = frappe.get_single("PowerPack Settings")
		doc.sales_margin_low_below, doc.sales_margin_medium_below, doc.sales_margin_good_below = 10, 5, 30
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
		doc.sales_margin_medium_below = 10
		doc.validate()  # equal neighbours just collapse a band
