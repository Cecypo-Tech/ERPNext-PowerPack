# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""POS minimum selling price = the sale's price list (ticked tills only).

Spec: docs/superpowers/specs/2026-11-02-pos-price-list-floor-design.md
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPosListFloorFields(FrappeTestCase):
	def test_fields_exist_after_setup(self):
		from cecypo_powerpack.pos_list_floor import ENFORCE_FIELD, LINE_LIST_FIELD, PIN_FIELD, setup_custom_fields

		setup_custom_fields()
		field = frappe.get_meta("POS Profile").get_field(ENFORCE_FIELD)
		self.assertEqual(field.label, "Enforce minimum selling price to selected pricelist")
		self.assertEqual(field.fieldtype, "Check")
		for doctype in ("Sales Invoice Item", "POS Invoice Item", "Sales Order Item"):
			self.assertTrue(frappe.get_meta(doctype).has_field(LINE_LIST_FIELD), doctype)
		self.assertEqual(frappe.get_meta("User").get_field(PIN_FIELD).fieldtype, "Password")

	def test_audit_fields_filterable_on_sales_invoice(self):
		meta = frappe.get_meta("Sales Invoice")
		self.assertTrue(meta.get_field("powerpack_price_approved_by").in_standard_filter)
		breach = meta.get_field("powerpack_price_breach")
		self.assertTrue(breach.in_standard_filter)
		self.assertFalse(breach.hidden)

	def test_pin_must_be_4_to_6_digits(self):
		from cecypo_powerpack.pos_list_floor import PIN_FIELD
		from cecypo_powerpack.pos_supervisor_pin import validate_pin_format

		for bad in ("123", "1234567", "12a4", " 1234"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				validate_pin_format(frappe._dict({PIN_FIELD: bad}))
		for good in ("1234", "123456", "", None, "*****"):
			validate_pin_format(frappe._dict({PIN_FIELD: good}))


ITEM = "_PLF Item"
RETAIL = "_PLF Retail"
DISTRIBUTOR = "_PLF Distributor"
EMPTY = "_PLF No Prices"
TILL = "_PLF Till"
CASHIER = "_plf_cashier@example.com"
VAT = "_Test Account VAT - _TC"


def ensure_plf_fixtures():
	"""Item at Retail 450 / Distributor 400 (Nos; Box = 10 Nos), and a ticked till.
	Committed so the per-test rollback cannot take them."""
	from cecypo_powerpack.pos_list_floor import ENFORCE_FIELD, setup_custom_fields

	setup_custom_fields()
	for name in (RETAIL, DISTRIBUTOR, EMPTY):
		if not frappe.db.exists("Price List", name):
			frappe.get_doc(
				{"doctype": "Price List", "price_list_name": name, "selling": 1, "currency": "INR", "enabled": 1}
			).insert(ignore_permissions=True)
	if not frappe.db.exists("Item", ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": ITEM,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"uoms": [{"uom": "Box", "conversion_factor": 10}],
			}
		).insert(ignore_permissions=True)
	for price_list, rate in ((RETAIL, 450), (DISTRIBUTOR, 400)):
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": ITEM, "price_list": price_list, "price_list_rate": rate, "uom": "Nos"}
			).insert(ignore_permissions=True)
	if not frappe.db.exists("POS Profile", TILL):
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": TILL,
				"company": "_Test Company",
				"cost_center": "_Test Cost Center - _TC",
				"currency": "INR",
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"income_account": "Sales - _TC",
				"selling_price_list": RETAIL,
				"warehouse": "_Test Warehouse - _TC",
				"write_off_account": "_Test Write Off - _TC",
				"write_off_cost_center": "_Test Write Off Cost Center - _TC",
				"payments": [{"mode_of_payment": "Cash", "default": 1}],
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("POS Profile", TILL, ENFORCE_FIELD, 1)
	if not frappe.db.exists("User", CASHIER):
		frappe.get_doc(
			{"doctype": "User", "email": CASHIER, "first_name": "PLF Cashier", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.db.commit()


def make_invoice(rate, header=RETAIL, line_list=None, uom="Nos", conversion_factor=1, vat=None, discount_pct=0, owner=None, till=TILL):
	"""An unsaved till Sales Invoice with totals computed, priced exactly as given."""
	from cecypo_powerpack.pos_list_floor import LINE_LIST_FIELD

	doc = frappe.new_doc("Sales Invoice")
	doc.update(
		{
			"company": "_Test Company",
			"customer": "_Test Customer",
			"currency": "INR",
			"conversion_rate": 1,
			"selling_price_list": header,
			"price_list_currency": "INR",
			"plc_conversion_rate": 1,
			"pos_profile": till,
			"posting_date": frappe.utils.nowdate(),
			"ignore_pricing_rule": 1,
			"owner": owner or "Administrator",
		}
	)
	doc.append(
		"items",
		{
			"item_code": ITEM,
			"item_name": ITEM,
			"qty": 1,
			"uom": uom,
			"stock_uom": "Nos",
			"conversion_factor": conversion_factor,
			"rate": rate,
			"price_list_rate": rate,
			LINE_LIST_FIELD: line_list,
		},
	)
	if vat:
		doc.append(
			"taxes",
			{"charge_type": "On Net Total", "account_head": VAT, "description": "VAT", "rate": vat, "included_in_print_rate": 1},
		)
	if discount_pct:
		doc.apply_discount_on = "Grand Total"
		doc.additional_discount_percentage = discount_pct
	doc.calculate_taxes_and_totals()
	return doc


def restrict_cashier_to_retail():
	if not frappe.db.exists("User Permission", {"user": CASHIER, "allow": "Price List"}):
		frappe.get_doc(
			{"doctype": "User Permission", "user": CASHIER, "allow": "Price List", "for_value": RETAIL}
		).insert(ignore_permissions=True)


def unrestrict_cashier():
	frappe.db.delete("User Permission", {"user": CASHIER})
	frappe.cache.hdel("user_permissions", CASHIER)


class TestPosListFloorRows(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_plf_fixtures()

	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_min_selling_price", 1)
		frappe.db.set_single_value("PowerPack Settings", "min_selling_price_skip_if_pricing_rule", 0)
		frappe.clear_cache(doctype="PowerPack Settings")

	def tearDown(self):
		unrestrict_cashier()
		super().tearDown()

	def minimums(self, doc):
		from cecypo_powerpack.pos_list_floor import below_floor_rows

		return [row["minimum"] for row in below_floor_rows(doc)]

	def test_spec_matrix(self):
		for header, rate, expected in (
			(RETAIL, 500, []),
			(RETAIL, 420, [450]),
			(RETAIL, 380, [450]),
			(DISTRIBUTOR, 500, []),
			(DISTRIBUTOR, 420, []),
			(DISTRIBUTOR, 380, [400]),
		):
			self.assertEqual(self.minimums(make_invoice(rate, header=header)), expected, (header, rate))

	def test_row_reports_what_the_cashier_sees(self):
		from cecypo_powerpack.pos_list_floor import below_floor_rows

		(row,) = below_floor_rows(make_invoice(420))
		self.assertEqual((row["idx"], row["item_code"], row["rate"], row["minimum"], row["price_list"]), (1, ITEM, 420, 450, RETAIL))

	def test_line_list_beats_header(self):
		self.assertEqual(self.minimums(make_invoice(420, header=RETAIL, line_list=DISTRIBUTOR)), [])

	def test_disallowed_line_list_ignored(self):
		restrict_cashier_to_retail()
		doc = make_invoice(420, header=RETAIL, line_list=DISTRIBUTOR, owner=CASHIER)
		self.assertEqual(self.minimums(doc), [450])

	def test_disallowed_header_falls_back_to_till_list(self):
		restrict_cashier_to_retail()
		self.assertEqual(self.minimums(make_invoice(420, header=DISTRIBUTOR, owner=CASHIER)), [450])

	def test_no_item_price_no_floor(self):
		self.assertEqual(self.minimums(make_invoice(1, header=EMPTY)), [])

	def test_uom_without_price_uses_conversion(self):
		self.assertEqual(self.minimums(make_invoice(4000, uom="Box", conversion_factor=10)), [4500])

	def test_inclusive_tax_at_list_passes(self):
		self.assertEqual(self.minimums(make_invoice(450, vat=16)), [])
		self.assertEqual(self.minimums(make_invoice(449.99, vat=16)), [450])

	def test_order_discount_counts(self):
		self.assertEqual(self.minimums(make_invoice(450, discount_pct=10)), [450])

	def test_pricing_rule_price_is_floor(self):
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": "_PLF Promo",
				"apply_on": "Item Code",
				"items": [{"item_code": ITEM}],
				"selling": 1,
				"company": "_Test Company",
				"currency": "INR",
				"price_or_product_discount": "Price",
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Pricing Rule", rule.name, force=1, ignore_permissions=True)
		self.assertEqual(self.minimums(make_invoice(405)), [450])
		frappe.db.set_single_value("PowerPack Settings", "min_selling_price_skip_if_pricing_rule", 1)
		frappe.clear_cache(doctype="PowerPack Settings")
		self.assertEqual(self.minimums(make_invoice(405)), [])
		self.assertEqual(self.minimums(make_invoice(400)), [405])
