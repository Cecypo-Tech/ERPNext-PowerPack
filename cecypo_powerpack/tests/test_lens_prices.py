"""Lens price lists on buying documents: priced lists, plus the others to add with (+).

On Purchase Order, Purchase Receipt and Purchase Invoice the lens shows only the selling
price lists that already price the item, offers the rest under "+ Add price list", and gives
a brand-new item one blank row for the default selling list so a price can be typed at once.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cecypo_powerpack.api import get_lens_data

OTHER_LIST = "_Test Lens Retail"


class TestLensPrices(IntegrationTestCase):
	def setUp(self):
		patcher = patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
		patcher.start()
		self.addCleanup(patcher.stop)
		if not frappe.db.exists("Price List", OTHER_LIST):
			frappe.get_doc({"doctype": "Price List", "price_list_name": OTHER_LIST, "selling": 1, "enabled": 1, "currency": "KES"}).insert()
		self.item = frappe.get_doc({"doctype": "Item", "item_code": f"_LENS-{frappe.generate_hash(length=6)}", "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 0}).insert().name
		self.default = frappe.db.get_single_value("Selling Settings", "selling_price_list")

	def selling_lists(self):
		return set(frappe.get_all("Price List", filters={"enabled": 1, "selling": 1}, pluck="name"))

	def test_a_new_item_gets_one_blank_row_for_the_default_list(self):
		for dt in ("Purchase Order", "Purchase Receipt", "Purchase Invoice"):
			data = get_lens_data(self.item, doctype=dt)
			self.assertEqual([r["price_list"] for r in data["price_lists"]], [self.default], dt)
			self.assertFalse(data["price_lists"][0]["item_price_name"])
			self.assertEqual(set(r["price_list"] for r in data["addable_price_lists"]), self.selling_lists() - {self.default})

	def test_a_priced_item_shows_only_its_lists_and_offers_the_rest(self):
		frappe.get_doc({"doctype": "Item Price", "item_code": self.item, "price_list": OTHER_LIST, "price_list_rate": 150}).insert()
		data = get_lens_data(self.item, doctype="Purchase Order")
		self.assertEqual([(r["price_list"], r["rate"]) for r in data["price_lists"]], [(OTHER_LIST, 150)])
		self.assertTrue(data["price_lists"][0]["item_price_name"])
		self.assertNotIn(OTHER_LIST, [r["price_list"] for r in data["addable_price_lists"]])
		self.assertIn(self.default, [r["price_list"] for r in data["addable_price_lists"]])

	def test_sales_documents_are_unchanged(self):
		data = get_lens_data(self.item, doctype="Quotation")
		self.assertEqual(data["price_lists"], [])
		self.assertNotIn("addable_price_lists", data)
