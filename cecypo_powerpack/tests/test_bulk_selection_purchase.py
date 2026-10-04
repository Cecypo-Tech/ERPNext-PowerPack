# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.api import _get_included_tax_rate, get_bulk_item_details


class TestBulkSelectionPurchase(FrappeTestCase):
	"""A Purchase Order's bulk dialog reads the PO's buying price list. Its Item Prices
	are flagged buying, not selling, and purchase-only items belong in the list."""

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("PowerPack Settings", {
			"enable_sales_order_bulk_selection": 1,
			"enable_purchase_order_bulk_selection": 1,
		})
		frappe.clear_cache(doctype="PowerPack Settings")
		frappe.cache().delete_value("powerpack_settings")

		suffix = frappe.generate_hash(length=6)
		currency = frappe.db.get_value("Company", frappe.db.get_value("Company", {}), "default_currency")
		self.price_list = frappe.get_doc({
			"doctype": "Price List",
			"price_list_name": f"_PP Buying {suffix}",
			"currency": currency,
			"buying": 1,
			"selling": 0,
		}).insert().name
		self.item = frappe.get_doc({
			"doctype": "Item",
			"item_code": f"_PP Purchase Only {suffix}",
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"is_sales_item": 0,
			"is_purchase_item": 1,
		}).insert().name
		frappe.get_doc({
			"doctype": "Item Price",
			"item_code": self.item,
			"price_list": self.price_list,
			"price_list_rate": 400,
		}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_cache(doctype="PowerPack Settings")
		frappe.cache().delete_value("powerpack_settings")

	def _rows(self, doctype, optimized=True):
		res = get_bulk_item_details(
			items=self.item, price_list=self.price_list, doctype=doctype, optimized=optimized
		)
		return {r["item_code"]: r for r in res["items"]}

	def test_purchase_order_gets_the_buying_price(self):
		for optimized in (True, False):
			with self.subTest(optimized=optimized):
				self.assertEqual(self._rows("Purchase Order", optimized)[self.item]["price_list_rate"], 400)

	def test_sales_order_still_skips_purchase_only_items(self):
		for optimized in (True, False):
			with self.subTest(optimized=optimized):
				self.assertNotIn(self.item, self._rows("Sales Order", optimized))

	def test_purchase_order_reads_the_purchase_tax_template(self):
		template = frappe._dict(taxes=[frappe._dict(included_in_print_rate=1, rate=16)])
		with patch("frappe.get_cached_doc", return_value=template) as get_doc:
			self.assertEqual(_get_included_tax_rate("Kenya Tax", buying=True), 16)
		get_doc.assert_called_once_with("Purchase Taxes and Charges Template", "Kenya Tax")
