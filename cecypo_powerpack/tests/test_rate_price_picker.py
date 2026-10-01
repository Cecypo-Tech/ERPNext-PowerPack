# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from unittest.mock import patch

from cecypo_powerpack.rate_price_picker import get_rate_options

COMPANY = "_Test Company"
CUSTOMER = "_Test Customer"
NO_ACCESS_USER = "pp-rate-picker-no-access@example.com"


def _item(last_purchase_rate=0):
	code = "_PP-RPP-" + frappe.generate_hash(length=8)
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"uoms": [{"uom": "Nos", "conversion_factor": 1}, {"uom": "Box", "conversion_factor": 12}],
		}
	).insert(ignore_permissions=True)
	if last_purchase_rate:
		frappe.db.set_value("Item", code, "last_purchase_rate", last_purchase_rate)
	return code


def _price_list(currency="INR", selling=1, buying=0):
	name = "_PP RPP " + frappe.generate_hash(length=6)
	frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": name,
			"currency": currency,
			"selling": selling,
			"buying": buying,
		}
	).insert(ignore_permissions=True)
	return name


def _disable(price_list):
	# After its prices are in: an Item Price cannot be added to a disabled list.
	frappe.db.set_value("Price List", price_list, "enabled", 0)


def _price(item_code, price_list, rate, **extra):
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"price_list_rate": rate,
			"uom": extra.pop("uom", "Nos"),
			**extra,
		}
	).insert(ignore_permissions=True)


def _options(item_code, **kwargs):
	args = {
		"doctype": "Quotation",
		"item_code": item_code,
		"uom": "Nos",
		"stock_uom": "Nos",
		"conversion_factor": 1,
		"currency": "INR",
		"customer": None,
		"company": COMPANY,
		"transaction_date": nowdate(),
		"conversion_rate": 1,
		"net_factor": 1,
	}
	args.update(kwargs)
	return get_rate_options(**args)["options"]


def _deny(kwargs):
	if kwargs.get("throw"):
		raise frappe.PermissionError
	return False


def _by_list(options):
	return {o["price_list"]: o for o in options}


class RatePickerTestCase(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_rate_price_picker", 1)
		frappe.db.set_single_value("PowerPack Settings", "enable_min_selling_price", 0)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache("PowerPack Settings", "PowerPack Settings")


class TestRateOptions(RatePickerTestCase):
	def test_one_line_per_selling_list_in_the_document_currency(self):
		item = _item()
		a, b = _price_list(), _price_list()
		usd, disabled, buying = _price_list("USD"), _price_list(), _price_list(selling=0, buying=1)
		_price(item, a, 500)
		_price(item, b, 450)
		for other in (usd, disabled, buying):
			_price(item, other, 9)
		_disable(disabled)

		options = _by_list(_options(item))

		self.assertEqual({a: 500, b: 450}, {k: v["rate"] for k, v in options.items()})

	def test_lists_without_a_price_for_the_item_are_left_out(self):
		item = _item()
		priced, _unpriced = _price_list(), _price_list()
		_price(item, priced, 500)

		self.assertEqual([o["price_list"] for o in _options(item)], [priced])

	def test_ordered_by_price_list_name(self):
		item = _item()
		lists = [_price_list() for _ in range(3)]
		for pl in lists:
			_price(item, pl, 100)

		self.assertEqual([o["price_list"] for o in _options(item)], sorted(lists))

	def test_customer_specific_price_wins(self):
		item = _item()
		pl = _price_list()
		_price(item, pl, 500)
		_price(item, pl, 450, customer=CUSTOMER)

		self.assertEqual(_by_list(_options(item, customer=CUSTOMER))[pl]["rate"], 450)
		self.assertEqual(_by_list(_options(item, customer="_Test Customer 1"))[pl]["rate"], 500)

	def test_stock_uom_price_is_scaled_to_the_row_uom(self):
		item = _item()
		pl = _price_list()
		_price(item, pl, 50)  # per Nos

		options = _by_list(_options(item, uom="Box", conversion_factor=12))

		self.assertEqual(options[pl]["rate"], 600)

	def test_a_price_for_the_row_uom_is_used_as_is(self):
		item = _item()
		pl = _price_list()
		_price(item, pl, 50)
		_price(item, pl, 540, uom="Box")

		self.assertEqual(_by_list(_options(item, uom="Box", conversion_factor=12))[pl]["rate"], 540)

	def test_a_variant_falls_back_to_its_templates_price(self):
		template, variant = _item(), _item()
		pl = _price_list()
		_price(template, pl, 300)  # before it is a template: ERPNext refuses prices on one
		frappe.db.set_value("Item", template, "has_variants", 1)
		frappe.db.set_value("Item", variant, "variant_of", template)
		frappe.clear_document_cache("Item", variant)

		self.assertEqual(_by_list(_options(variant))[pl]["rate"], 300)

	def test_expired_price_is_left_out(self):
		item = _item()
		pl = _price_list()
		_price(item, pl, 500, valid_from=add_days(nowdate(), -30), valid_upto=add_days(nowdate(), -1))

		self.assertEqual(_options(item), [])


class TestBelowFloor(RatePickerTestCase):
	"""Floor = last purchase rate 100 x (1 + 10%) = 110 per stock unit, net, company currency."""

	def setUp(self):
		super().setUp()
		frappe.db.set_single_value(
			"PowerPack Settings",
			{
				"enable_min_selling_price": 1,
				"min_selling_price_default_basis": "Last Purchase Rate",
				"min_selling_price_default_percent": 10,
				"min_selling_price_whole_sale": 0,
			},
		)
		frappe.clear_document_cache("PowerPack Settings", "PowerPack Settings")
		self.item = _item(last_purchase_rate=100)
		self.low, self.high = _price_list(), _price_list()
		_price(self.item, self.low, 105)
		_price(self.item, self.high, 120)

	def _flags(self, **kwargs):
		return {k: v["below_floor"] for k, v in _by_list(_options(self.item, **kwargs)).items()}

	def test_marks_only_prices_below_the_floor(self):
		self.assertEqual(self._flags(), {self.low: True, self.high: False})

	def test_compares_net_of_inclusive_tax(self):
		# 120 including 16% VAT is 103.45 net - below 110.
		self.assertEqual(self._flags(net_factor=1 / 1.16), {self.low: True, self.high: True})

	def test_compares_in_company_currency(self):
		# 105 at 2 company-currency units each is 210 - above 110.
		self.assertEqual(self._flags(conversion_rate=2), {self.low: False, self.high: False})

	def test_floor_scales_with_the_row_uom(self):
		# A Box of 12 floors at 1320; the Nos prices x 12 are 1260 and 1440.
		self.assertEqual(self._flags(uom="Box", conversion_factor=12), {self.low: True, self.high: False})

	def test_no_marks_on_a_pricing_rule_row_when_those_are_exempt(self):
		frappe.db.set_single_value("PowerPack Settings", "min_selling_price_skip_if_pricing_rule", 1)
		frappe.clear_document_cache("PowerPack Settings", "PowerPack Settings")

		self.assertEqual(self._flags(has_pricing_rule=1), {self.low: False, self.high: False})
		self.assertEqual(self._flags(has_pricing_rule=0), {self.low: True, self.high: False})

	def test_no_marks_when_minimum_selling_price_is_off(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_min_selling_price", 0)
		frappe.clear_document_cache("PowerPack Settings", "PowerPack Settings")

		self.assertEqual(self._flags(), {self.low: False, self.high: False})


class TestGuards(RatePickerTestCase):
	def test_returns_nothing_when_the_setting_is_off(self):
		# Not an error: a browser still holding the old setting would show a dialog on
		# every Rate focus.
		item = _item()
		_price(item, _price_list(), 500)
		frappe.db.set_single_value("PowerPack Settings", "enable_rate_price_picker", 0)

		self.assertEqual(_options(item), [])

	def test_refuses_an_item_the_user_cannot_read(self):
		item = _item()
		with patch("frappe.has_permission", side_effect=lambda doctype, *a, **kw: doctype != "Item" or _deny(kw)):
			with self.assertRaises(frappe.PermissionError):
				_options(item)

	def test_refuses_other_doctypes(self):
		with self.assertRaises(frappe.ValidationError):
			_options(_item(), doctype="Purchase Order")

	def test_refuses_a_user_who_cannot_read_the_doctype(self):
		item = _item()
		if not frappe.db.exists("User", NO_ACCESS_USER):
			frappe.get_doc(
				{"doctype": "User", "email": NO_ACCESS_USER, "first_name": "No Access", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(NO_ACCESS_USER)

		with self.assertRaises(frappe.PermissionError):
			_options(item)


class TestListPriceWriteBack(RatePickerTestCase):
	"""With Stock Settings writing the row's Price List Rate back to the document's price list,
	a pick that changed the list price would rewrite that list's Item Price on save."""

	def _set_list_price(self, auto_insert, based_on):
		frappe.db.set_single_value(
			"Stock Settings",
			{"auto_insert_price_list_rate_if_missing": auto_insert, "update_price_list_based_on": based_on},
		)
		frappe.clear_document_cache("Stock Settings", "Stock Settings")
		item = _item()
		_price(item, _price_list(), 500)
		args = dict(doctype="Quotation", item_code=item, uom="Nos", stock_uom="Nos", conversion_factor=1,
			currency="INR", company=COMPANY, transaction_date=nowdate())
		return get_rate_options(**args)["set_list_price"]

	def test_sets_the_list_price_normally(self):
		self.assertTrue(self._set_list_price(0, "Price List Rate"))
		self.assertTrue(self._set_list_price(1, "Rate"))

	def test_sets_only_the_rate_when_the_list_price_would_be_written_back(self):
		self.assertFalse(self._set_list_price(1, "Price List Rate"))
