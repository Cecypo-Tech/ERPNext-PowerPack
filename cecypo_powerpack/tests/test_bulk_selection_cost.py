# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

ITEM = "_Test Item"


class TestBulkSelectionCost(FrappeTestCase):
	"""The bulk dialog hides its cost column from users outside has_cost_permission()
	(bulk_selection.js); the server has to withhold the value too, or anyone can read it
	straight off the endpoint."""

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("PowerPack Settings", {
			"enable_sales_order_bulk_selection": 1,
			"enable_stock_reconciliation_bulk_selection": 1,
		})
		frappe.clear_cache(doctype="PowerPack Settings")
		frappe.cache().delete_value("powerpack_settings")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_cache(doctype="PowerPack Settings")
		frappe.cache().delete_value("powerpack_settings")

	def _user(self, roles, user_type="System User"):
		return frappe.get_doc({
			"doctype": "User",
			"email": f"pp-bulk-{frappe.generate_hash(length=6)}@example.com",
			"first_name": "Bulk Test",
			"user_type": user_type,
			"send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}).insert(ignore_permissions=True).name

	def _sales(self):
		from cecypo_powerpack.api import get_bulk_item_details

		res = get_bulk_item_details(items=ITEM, price_list="Standard Selling", doctype="Sales Order")
		return {r["item_code"]: r for r in res["items"]}[ITEM]

	def test_cost_roles_get_the_valuation_rate(self):
		self.assertIsNotNone(self._sales()["valuation_rate"])

	def test_sales_user_gets_no_valuation_rate(self):
		frappe.set_user(self._user(["Sales User"]))
		self.assertIsNone(self._sales()["valuation_rate"])

	def test_sales_endpoint_refuses_users_without_read_on_the_doctype(self):
		frappe.set_user(self._user(["Customer"], user_type="Website User"))
		with self.assertRaises(frappe.PermissionError):
			self._sales()

	def test_stock_endpoint_refuses_users_without_read_on_the_doctype(self):
		from cecypo_powerpack.api import get_bulk_stock_item_details

		frappe.set_user(self._user(["Sales User"]))
		with self.assertRaises(frappe.PermissionError):
			get_bulk_stock_item_details(items=ITEM, doctype="Stock Reconciliation")
