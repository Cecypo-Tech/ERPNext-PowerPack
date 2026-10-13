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

	# A site hides cost by moving Item.valuation_rate to a permlevel only some roles can
	# read (Allparts: "Cost Viewer"). Both endpoints have to honour that, or the dialog
	# shows the cost the form hides.

	def _item_cost_permlevel(self, level):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		make_property_setter("Item", "valuation_rate", "permlevel", str(level), "Int", validate_fields_for_doctype=False)
		frappe.clear_cache(doctype="Item")
		self.addCleanup(frappe.clear_cache, doctype="Item")

	def _restrict_item_cost(self):
		self._item_cost_permlevel(1)

	def _stock(self):
		from cecypo_powerpack.api import get_bulk_stock_item_details

		frappe.db.set_single_value("PowerPack Settings", "enable_stock_entry_bulk_selection", 1)
		frappe.cache().delete_value("powerpack_settings")
		res = get_bulk_stock_item_details(items=ITEM, doctype="Stock Entry")
		return {r["item_code"]: r for r in res["items"]}[ITEM]

	def test_stock_user_gets_the_valuation_rate_when_cost_is_not_restricted(self):
		self._item_cost_permlevel(0)
		frappe.set_user(self._user(["Stock User"]))
		self.assertIsNotNone(self._stock()["valuation_rate"])

	def test_stock_user_gets_no_valuation_rate_when_cost_is_restricted(self):
		self._restrict_item_cost()
		frappe.set_user(self._user(["Stock User"]))
		self.assertIsNone(self._stock()["valuation_rate"])

	def test_cost_role_without_access_to_the_restricted_field_gets_no_valuation_rate(self):
		self._restrict_item_cost()
		frappe.set_user(self._user(["Sales User", "Accounts Manager"]))
		self.assertIsNone(self._sales()["valuation_rate"])

	def test_cost_viewer_role_counts_as_a_cost_role(self):
		if not frappe.db.exists("Role", "Cost Viewer"):
			frappe.get_doc({"doctype": "Role", "role_name": "Cost Viewer"}).insert(ignore_permissions=True)
		self._item_cost_permlevel(0)
		frappe.set_user(self._user(["Sales User", "Cost Viewer"]))
		self.assertIsNotNone(self._sales()["valuation_rate"])
